#!/usr/bin/env python3
"""
批量实验脚本：对每个 (数据集, 查询图) 对，跑所有有效 (filter, order) 组合的
filter-order 阶段，记录输出的查询序列。

输出 CSV 格式:
  dataset, query_file, query_vertices, query_edges, filter, order,
  sequence, filter_time, plan_time, preprocessing_time, status

用法:
    python tools/run_filter_order_experiment.py \
        --dataset_dir dataset \
        --output results/m1_sequences.csv \
        --workers 8 \
        --time_limit 30

只需要 filter-order 阶段的结果（查询序列），不需要完整枚举。
使用 -num 1 跳过枚举阶段以加速。
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

BINARY = (
    PROJECT_ROOT
    / "core"
    / "engines"
    / "SubgraphMatchingSurvey"
    / "vlabel"
    / "build"
    / "matching"
    / "SubgraphMatching.out"
)

# 81 种有效 (filter, order) 组合（排除 CECI）
VALID_FILTERS = ["LDF", "NLF", "GQL", "TSO", "CFL", "DPiso", "VEQ", "RM", "CaLiG"]
VALID_ORDERS = ["QSI", "GQL", "TSO", "CFL", "DPiso", "RI", "VF2PP", "VF3", "RM"]

# 正则
RE_QUERY_PLAN = re.compile(r"Query Plan:\s*(.+)")
RE_FILTER_TIME = re.compile(r"Filter vertices time \(seconds\):\s*([\d.]+)")
RE_PLAN_TIME = re.compile(r"Generate query plan time \(seconds\):\s*([\d.]+)")
RE_PREPROCESS_TIME = re.compile(r"Preprocessing time \(seconds\):\s*([\d.]+)")
RE_HEADER = re.compile(r"^t\s+(\d+)\s+(\d+)")

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def parse_query_header(query_path: str) -> tuple[int, int]:
    """读取查询图的 |V| 和 |E|。"""
    with open(query_path) as f:
        for line in f:
            m = RE_HEADER.match(line.strip())
            if m:
                return int(m.group(1)), int(m.group(2))
    return 0, 0


def build_subprocess_env() -> dict[str, str]:
    """确保 LD_LIBRARY_PATH 包含 Survey 的 .so 目录。"""
    env = os.environ.copy()
    lib_dirs = [
        str(BINARY.parent.parent / "graph"),
        str(BINARY.parent.parent / "utility"),
        str(BINARY.parent.parent / "utility" / "nucleus_decomposition"),
        str(BINARY.parent.parent / "utility" / "execution_tree"),
    ]
    existing = env.get("LD_LIBRARY_PATH", "")
    entries = [d for d in lib_dirs if os.path.isdir(d)]
    if existing:
        entries.append(existing)
    env["LD_LIBRARY_PATH"] = ":".join(entries)
    return env


ENV = build_subprocess_env()


def run_single(
    data_graph: str,
    query_graph: str,
    filter_type: str,
    order_type: str,
    time_limit: int,
) -> dict[str, str]:
    """
    运行一次 Survey filter-order 阶段，返回解析结果 dict。
    """
    cmd = [
        str(BINARY),
        "-d", data_graph,
        "-q", query_graph,
        "-filter", filter_type,
        "-order", order_type,
        "-engine", "LFTJ",       # engine 不影响 filter-order 结果
        "-num", "1",             # 跳过枚举
        "-time_limit", str(time_limit),
    ]

    timeout = time_limit + 15

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=ENV,
        )
        stdout = proc.stdout
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return {
            "sequence": "",
            "filter_time": "",
            "plan_time": "",
            "preprocessing_time": "",
            "status": "TIMEOUT",
        }
    except Exception as e:
        return {
            "sequence": "",
            "filter_time": "",
            "plan_time": "",
            "preprocessing_time": "",
            "status": f"ERROR:{e}",
        }

    if rc != 0:
        return {
            "sequence": "",
            "filter_time": "",
            "plan_time": "",
            "preprocessing_time": "",
            "status": f"CRASH:rc={rc}",
        }

    # 解析
    m_plan = RE_QUERY_PLAN.search(stdout)
    m_ft = RE_FILTER_TIME.search(stdout)
    m_pt = RE_PLAN_TIME.search(stdout)
    m_pp = RE_PREPROCESS_TIME.search(stdout)

    sequence = m_plan.group(1).strip() if m_plan else ""

    return {
        "sequence": sequence,
        "filter_time": m_ft.group(1) if m_ft else "",
        "plan_time": m_pt.group(1) if m_pt else "",
        "preprocessing_time": m_pp.group(1) if m_pp else "",
        "status": "OK" if sequence else "NO_PLAN",
    }


# ---------------------------------------------------------------------------
# 任务封装（用于多进程 map）
# ---------------------------------------------------------------------------

def _task_wrapper(args: tuple) -> dict[str, str]:
    (dataset_name, data_graph, query_file, query_basename,
     nv, ne, ft, ot, time_limit) = args

    result = run_single(data_graph, query_file, ft, ot, time_limit)
    result["dataset"] = dataset_name
    result["query_file"] = query_basename
    result["query_vertices"] = str(nv)
    result["query_edges"] = str(ne)
    result["filter"] = ft
    result["order"] = ot
    return result


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "dataset", "query_file", "query_vertices", "query_edges",
    "filter", "order", "sequence",
    "filter_time", "plan_time", "preprocessing_time", "status",
]


def discover_datasets(dataset_dir: str) -> list[tuple[str, str]]:
    """发现所有 (dataset_name, data_graph_path) 对。"""
    results = []
    for entry in sorted(os.listdir(dataset_dir)):
        d = os.path.join(dataset_dir, entry)
        if not os.path.isdir(d):
            continue
        graph_file = os.path.join(d, f"{entry}.graph")
        if os.path.isfile(graph_file):
            results.append((entry, graph_file))
    return results


def discover_queries(dataset_dir: str, dataset_name: str) -> list[str]:
    """发现某个数据集下的所有查询图文件。"""
    query_dir = os.path.join(dataset_dir, dataset_name, "gen_query_graph")
    if not os.path.isdir(query_dir):
        return []
    files = sorted(
        f for f in os.listdir(query_dir)
        if f.endswith(".graph")
    )
    return [os.path.join(query_dir, f) for f in files]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="批量运行 filter-order 组合，记录查询序列"
    )
    parser.add_argument(
        "--dataset_dir", default=str(PROJECT_ROOT / "dataset"),
        help="数据集根目录 (default: <project>/dataset)",
    )
    parser.add_argument(
        "--output", default=str(PROJECT_ROOT / "results" / "m1_sequences.csv"),
        help="输出 CSV 路径",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="并行工作进程数",
    )
    parser.add_argument(
        "--time_limit", type=int, default=30,
        help="每次运行的时间限制 (秒)",
    )
    parser.add_argument(
        "--datasets", nargs="*", default=None,
        help="只跑指定数据集 (默认全部)",
    )
    parser.add_argument(
        "--query_pattern", default=None,
        help="查询图文件名过滤 (子串匹配, 如 'dense_16')",
    )

    args = parser.parse_args()

    # 发现数据集
    all_datasets = discover_datasets(args.dataset_dir)
    if args.datasets:
        allowed = set(args.datasets)
        all_datasets = [(n, p) for n, p in all_datasets if n in allowed]

    if not all_datasets:
        print("ERROR: No datasets found in", args.dataset_dir, file=sys.stderr)
        sys.exit(1)

    print(f"Datasets found: {[n for n, _ in all_datasets]}")

    # 构建任务列表
    tasks: list[tuple] = []
    for dataset_name, data_graph in all_datasets:
        queries = discover_queries(args.dataset_dir, dataset_name)
        if args.query_pattern:
            queries = [q for q in queries if args.query_pattern in os.path.basename(q)]

        print(f"  {dataset_name}: {len(queries)} query graphs "
              f"× {len(VALID_FILTERS)}×{len(VALID_ORDERS)}={len(VALID_FILTERS)*len(VALID_ORDERS)} combos "
              f"= {len(queries) * len(VALID_FILTERS) * len(VALID_ORDERS)} tasks")

        for qf in queries:
            nv, ne = parse_query_header(qf)
            qbasename = os.path.basename(qf)
            for ft in VALID_FILTERS:
                for ot in VALID_ORDERS:
                    tasks.append((
                        dataset_name, data_graph, qf, qbasename,
                        nv, ne, ft, ot, args.time_limit,
                    ))

    total = len(tasks)
    print(f"\nTotal tasks: {total}")
    if total == 0:
        print("Nothing to do.")
        return

    # 创建输出目录
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    # 执行
    completed = 0
    ok_count = 0

    with open(args.output, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        writer.writeheader()

        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_task_wrapper, t): t for t in tasks}

            for future in as_completed(futures):
                completed += 1
                result = future.result()
                writer.writerow(result)

                if result["status"] == "OK":
                    ok_count += 1

                if completed % 500 == 0 or completed == total:
                    csvfile.flush()
                    pct = completed * 100 / total
                    print(
                        f"  [{completed}/{total}] {pct:.1f}% done, "
                        f"{ok_count} OK",
                        flush=True,
                    )

    print(f"\nFinished: {ok_count}/{total} OK")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
