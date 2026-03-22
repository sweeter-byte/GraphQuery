#!/usr/bin/env python3
"""
补充脚本 B：提取每种 filter 对每个查询图的候选集特征。

对每个 (dataset, query_graph, filter) 三元组运行一次 C++ 二进制，
使用 -num 1 跳过枚举，仅执行 filter 阶段，解析候选集信息。

候选集只取决于 (dataset, query, filter)，与 order 无关，
因此只需跑 9 种 filter（而非 81 种 filter×order 组合）。

输出 CSV 格式:
    dataset, query_file, filter, candidates_per_vertex,
    total_candidates, min_candidates, max_candidates,
    avg_candidates, filter_time, status

用法:
    python tools/extract_candidate_features.py --dataset_dir dataset
    python tools/extract_candidate_features.py --datasets yeast --workers 4
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

# 9 种 filter（排除 CECI，因为它需要特殊数据结构）
VALID_FILTERS = ["LDF", "NLF", "GQL", "TSO", "CFL", "DPiso", "VEQ", "RM", "CaLiG"]

# 固定使用 QSI order 和 LFTJ engine，不影响 filter 阶段结果
FIXED_ORDER = "QSI"
FIXED_ENGINE = "LFTJ"

# 正则：解析 stdout
RE_CANDIDATES_PER_VERTEX = re.compile(r"Candidates Per Vertex:([\d,]+)")
RE_TOTAL_CANDIDATES = re.compile(r"Total Candidates:\s*(\d+)")
RE_FILTER_TIME = re.compile(r"Filter vertices time \(seconds\):\s*([\d.]+)")


# ---------------------------------------------------------------------------
# 环境
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 单次运行
# ---------------------------------------------------------------------------

def run_single(
    data_graph: str,
    query_graph: str,
    filter_type: str,
    time_limit: int,
) -> dict[str, str]:
    """运行一次 filter 阶段，解析候选集信息。"""
    cmd = [
        str(BINARY),
        "-d", data_graph,
        "-q", query_graph,
        "-filter", filter_type,
        "-order", FIXED_ORDER,
        "-engine", FIXED_ENGINE,
        "-num", "1",                  # 跳过枚举
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
        return {"status": "TIMEOUT"}
    except Exception as e:
        return {"status": f"ERROR:{e}"}

    if rc != 0:
        return {"status": f"CRASH:rc={rc}"}

    # 解析候选集
    m_cpv = RE_CANDIDATES_PER_VERTEX.search(stdout)
    m_total = RE_TOTAL_CANDIDATES.search(stdout)
    m_ft = RE_FILTER_TIME.search(stdout)

    if not m_cpv:
        return {"status": "NO_CANDIDATES"}

    cpv_str = m_cpv.group(1)  # e.g. "21,162,196,2"
    counts = [int(x) for x in cpv_str.split(",")]

    return {
        "candidates_per_vertex": cpv_str,
        "total_candidates": m_total.group(1) if m_total else str(sum(counts)),
        "min_candidates": str(min(counts)),
        "max_candidates": str(max(counts)),
        "avg_candidates": str(round(sum(counts) / len(counts), 2)),
        "filter_time": m_ft.group(1) if m_ft else "",
        "status": "OK",
    }


# ---------------------------------------------------------------------------
# 任务封装
# ---------------------------------------------------------------------------

def _task_wrapper(args: tuple) -> dict[str, str]:
    dataset_name, data_graph, query_file, query_basename, ft, time_limit = args

    result = run_single(data_graph, query_file, ft, time_limit)
    result["dataset"] = dataset_name
    result["query_file"] = query_basename
    result["filter"] = ft

    # 如果失败，填充空值
    for key in ("candidates_per_vertex", "total_candidates",
                "min_candidates", "max_candidates",
                "avg_candidates", "filter_time"):
        result.setdefault(key, "")

    return result


# ---------------------------------------------------------------------------
# 发现文件
# ---------------------------------------------------------------------------

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
    for subdir in ("gen_query_graph", "query_graph"):
        query_dir = os.path.join(dataset_dir, dataset_name, subdir)
        if os.path.isdir(query_dir):
            files = sorted(
                f for f in os.listdir(query_dir)
                if f.endswith(".graph")
            )
            return [os.path.join(query_dir, f) for f in files]
    return []


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "dataset", "query_file", "filter",
    "candidates_per_vertex", "total_candidates",
    "min_candidates", "max_candidates", "avg_candidates",
    "filter_time", "status",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="补充脚本 B：提取每种 filter 的候选集特征"
    )
    parser.add_argument(
        "--dataset_dir", default=str(PROJECT_ROOT / "dataset"),
        help="数据集根目录 (default: <project>/dataset)",
    )
    parser.add_argument(
        "--output", default=str(PROJECT_ROOT / "results" / "candidate_features.csv"),
        help="输出 CSV 路径",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="并行工作进程数",
    )
    parser.add_argument(
        "--time_limit", type=int, default=60,
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
    parser.add_argument(
        "--filters", nargs="*", default=None,
        help="只跑指定 filter (默认全部 9 种)",
    )

    args = parser.parse_args()

    filters = args.filters if args.filters else VALID_FILTERS

    # 发现数据集
    all_datasets = discover_datasets(args.dataset_dir)
    if args.datasets:
        allowed = set(args.datasets)
        all_datasets = [(n, p) for n, p in all_datasets if n in allowed]

    if not all_datasets:
        print("ERROR: No datasets found in", args.dataset_dir, file=sys.stderr)
        sys.exit(1)

    print(f"Datasets: {[n for n, _ in all_datasets]}")
    print(f"Filters:  {filters}")

    # 构建任务列表
    tasks: list[tuple] = []
    for dataset_name, data_graph in all_datasets:
        queries = discover_queries(args.dataset_dir, dataset_name)
        if args.query_pattern:
            queries = [q for q in queries if args.query_pattern in os.path.basename(q)]

        print(f"  {dataset_name}: {len(queries)} query graphs × {len(filters)} filters "
              f"= {len(queries) * len(filters)} tasks")

        for qf in queries:
            qbasename = os.path.basename(qf)
            for ft in filters:
                tasks.append((
                    dataset_name, data_graph, qf, qbasename,
                    ft, args.time_limit,
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
                writer.writerow({k: result[k] for k in FIELDNAMES})

                if result["status"] == "OK":
                    ok_count += 1

                if completed % 200 == 0 or completed == total:
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
