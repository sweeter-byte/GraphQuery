#!/usr/bin/env python3
"""
M3 引擎实验脚本：对 order_data CSV 中每条有效序列，用所有兼容引擎执行
真实枚举，记录 embedding count、耗时等指标。

输入: order_data/<dataset>.csv  (M1 生成的序列数据)
输出 CSV 格式:
  dataset, query_file, query_vertices, query_edges, filter, order, engine,
  sequence, embedding_count, total_time, enum_time, filter_time,
  build_table_time, plan_time, preprocessing_time, memory_mb,
  call_count, eps, status

用法:
    python tools/run_m3_engine_experiment.py \
        --dataset_dir dataset \
        --order_csv order_data/yeast.csv \
        --output results/m3_engines_yeast.csv \
        --workers 8 \
        --time_limit 60

    # 只跑部分引擎
    python tools/run_m3_engine_experiment.py \
        --order_csv order_data/yeast.csv \
        --output results/m3_engines_yeast.csv \
        --engines LFTJ EXPLORE GQL

    # 按查询图名过滤
    python tools/run_m3_engine_experiment.py \
        --order_csv order_data/yeast.csv \
        --output results/m3_engines_yeast_dense_8.csv \
        --query_pattern dense_8
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
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

# 支持 CUSTOM order 的引擎 (排除 VEQ/DPiso/CECI/Spectrum)
VALID_ENGINES = ["EXPLORE", "LFTJ", "GQL", "QSI", "VF3", "RM", "KSS"]

# 解析正则
RE_EMBEDDINGS = re.compile(r"#Embeddings:\s*(\d+)")
RE_TOTAL_TIME = re.compile(r"Total time \(seconds\):\s*([\d.]+)")
RE_ENUM_TIME = re.compile(r"Enumerate time \(seconds\):\s*([\d.]+)")
RE_FILTER_TIME = re.compile(r"Filter vertices time \(seconds\):\s*([\d.]+)")
RE_BUILD_TABLE_TIME = re.compile(r"Build table time \(seconds\):\s*([\d.]+)")
RE_PLAN_TIME = re.compile(r"Generate query plan time \(seconds\):\s*([\d.]+)")
RE_PREPROCESS_TIME = re.compile(r"Preprocessing time \(seconds\):\s*([\d.]+)")
RE_MEMORY = re.compile(r"Memory cost \(MB\):\s*([\d.]+)")
RE_CALL_COUNT = re.compile(r"Call Count:\s*(\d+)")

M3_FIELDNAMES = [
    "dataset", "query_file", "query_vertices", "query_edges",
    "filter", "order", "engine", "sequence",
    "embedding_count", "total_time", "enum_time", "filter_time",
    "build_table_time", "plan_time", "preprocessing_time",
    "memory_mb", "call_count", "eps", "status",
]

# ---------------------------------------------------------------------------
# 环境
# ---------------------------------------------------------------------------


def build_subprocess_env() -> dict[str, str]:
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
# 核心执行
# ---------------------------------------------------------------------------


def sequence_to_order(sequence: str) -> list[int]:
    """将 M1 的 sequence 字符串转为顶点 ID 列表。

    支持格式:
      - 空格分隔: "2 0 3 1"
      - 横杠分隔: "2-0-3-1"
      - 逗号分隔: "2,0,3,1"
    """
    seq = sequence.strip()
    if not seq:
        return []
    # 统一分隔符
    for sep in ["-", ","]:
        seq = seq.replace(sep, " ")
    return [int(x) for x in seq.split()]


def run_single_engine(
    data_graph: str,
    query_graph: str,
    filter_type: str,
    engine_type: str,
    order_ids: list[int],
    time_limit: int,
) -> dict[str, str]:
    """用指定引擎和 CUSTOM order 执行一次完整枚举。"""

    # 写临时 order 文件
    fd, order_file = tempfile.mkstemp(prefix="m3_order_", suffix=".txt")
    try:
        os.write(fd, (" ".join(str(v) for v in order_ids) + "\n").encode())
        os.close(fd)

        cmd = [
            str(BINARY),
            "-d", data_graph,
            "-q", query_graph,
            "-filter", filter_type,
            "-order", "CUSTOM",
            "-order_file", order_file,
            "-engine", engine_type,
            "-num", "MAX",
            "-time_limit", str(time_limit),
        ]

        timeout = time_limit + 30

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, env=ENV,
            )
            stdout = proc.stdout
            rc = proc.returncode
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or b"")
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            return _parse_output(stdout, "TIMEOUT")
        except Exception as e:
            return _empty_result(f"ERROR:{e}")

        if rc != 0:
            return _parse_output(stdout, f"CRASH:rc={rc}")

        return _parse_output(stdout, "OK")
    finally:
        if os.path.exists(order_file):
            os.remove(order_file)


def _parse_output(stdout: str, status: str) -> dict[str, str]:
    def _ex_int(pat, text):
        m = pat.search(text)
        return m.group(1) if m else ""

    def _ex_float(pat, text):
        m = pat.search(text)
        return m.group(1) if m else ""

    emb = _ex_int(RE_EMBEDDINGS, stdout)
    total = _ex_float(RE_TOTAL_TIME, stdout)
    enum_t = _ex_float(RE_ENUM_TIME, stdout)

    # 计算 EPS
    eps = ""
    try:
        if emb and total and float(total) > 0:
            eps = f"{int(emb) / float(total):.2f}"
    except (ValueError, ZeroDivisionError):
        pass

    return {
        "embedding_count": emb,
        "total_time": total,
        "enum_time": enum_t,
        "filter_time": _ex_float(RE_FILTER_TIME, stdout),
        "build_table_time": _ex_float(RE_BUILD_TABLE_TIME, stdout),
        "plan_time": _ex_float(RE_PLAN_TIME, stdout),
        "preprocessing_time": _ex_float(RE_PREPROCESS_TIME, stdout),
        "memory_mb": _ex_float(RE_MEMORY, stdout),
        "call_count": _ex_int(RE_CALL_COUNT, stdout),
        "eps": eps,
        "status": status,
    }


def _empty_result(status: str) -> dict[str, str]:
    return {k: "" for k in M3_FIELDNAMES[8:]}  | {"status": status}


# ---------------------------------------------------------------------------
# 任务封装 (多进程)
# ---------------------------------------------------------------------------


def _task_wrapper(args: tuple) -> dict[str, str]:
    (dataset_name, data_graph, query_graph, query_basename,
     nv, ne, filter_type, order_type, engine_type,
     sequence, order_ids, time_limit) = args

    result = run_single_engine(
        data_graph, query_graph, filter_type, engine_type,
        order_ids, time_limit,
    )
    result["dataset"] = dataset_name
    result["query_file"] = query_basename
    result["query_vertices"] = str(nv)
    result["query_edges"] = str(ne)
    result["filter"] = filter_type
    result["order"] = order_type
    result["engine"] = engine_type
    result["sequence"] = sequence
    return result


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="M3: 对 M1 序列用多引擎执行真实枚举"
    )
    parser.add_argument(
        "--dataset_dir", default=str(PROJECT_ROOT / "dataset"),
        help="数据集根目录 (default: <project>/dataset)",
    )
    parser.add_argument(
        "--order_csv", required=True,
        help="M1 输出的 order_data/<dataset>.csv",
    )
    parser.add_argument(
        "--output", required=True,
        help="M3 输出 CSV 路径",
    )
    parser.add_argument(
        "--engines", nargs="*", default=None,
        help=f"要跑的引擎列表 (默认全部: {VALID_ENGINES})",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="并行工作进程数",
    )
    parser.add_argument(
        "--time_limit", type=int, default=60,
        help="每次枚举的时间限制 (秒)",
    )
    parser.add_argument(
        "--query_pattern", default=None,
        help="查询图文件名过滤 (子串匹配, 如 'dense_8')",
    )
    parser.add_argument(
        "--max_embeddings", default="MAX",
        help="最大枚举数 (默认 MAX = 无限制)",
    )

    args = parser.parse_args()

    engines = args.engines or VALID_ENGINES
    for eng in engines:
        if eng not in VALID_ENGINES:
            print(f"WARNING: engine '{eng}' not in supported list {VALID_ENGINES}",
                  file=sys.stderr)

    # 读取 M1 CSV
    if not os.path.isfile(args.order_csv):
        print(f"ERROR: order CSV not found: {args.order_csv}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with open(args.order_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 只处理 OK 且有 sequence 的行
            if row.get("status", "").strip() != "OK":
                continue
            seq = row.get("sequence", "").strip()
            if not seq:
                continue
            if args.query_pattern and args.query_pattern not in row.get("query_file", ""):
                continue
            rows.append(row)

    print(f"Loaded {len(rows)} valid rows from {args.order_csv}")
    print(f"Engines: {engines}")

    if not rows:
        print("Nothing to do.")
        return

    # 推断数据集名和路径
    dataset_name = rows[0]["dataset"].strip()
    data_graph = os.path.join(args.dataset_dir, dataset_name, f"{dataset_name}.graph")
    if not os.path.isfile(data_graph):
        print(f"ERROR: data graph not found: {data_graph}", file=sys.stderr)
        sys.exit(1)

    # 推断查询图目录
    query_dir = os.path.join(args.dataset_dir, dataset_name, "gen_query_graph")
    if not os.path.isdir(query_dir):
        query_dir = os.path.join(args.dataset_dir, dataset_name, "query_graph")

    print(f"Dataset: {dataset_name}, data graph: {data_graph}")
    print(f"Query dir: {query_dir}")

    # 去重: 同一个 (query_file, filter, sequence) 只需跑一次每个 engine
    # 不同 order 可能产生相同 sequence, 避免重复执行
    seen = set()
    tasks: list[tuple] = []

    for row in rows:
        qbasename = row["query_file"].strip()
        ft = row["filter"].strip()
        ot = row["order"].strip()
        seq = row["sequence"].strip()
        nv = row.get("query_vertices", "0").strip()
        ne = row.get("query_edges", "0").strip()

        order_ids = sequence_to_order(seq)
        if not order_ids:
            continue

        query_graph = os.path.join(query_dir, qbasename)
        if not os.path.isfile(query_graph):
            continue

        for eng in engines:
            dedup_key = (qbasename, ft, seq, eng)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            tasks.append((
                dataset_name, data_graph, query_graph, qbasename,
                nv, ne, ft, ot, eng, seq, order_ids, args.time_limit,
            ))

    total = len(tasks)
    print(f"Total tasks: {total} ({len(rows)} rows × {len(engines)} engines, "
          f"after dedup)")

    if total == 0:
        print("Nothing to do.")
        return

    # 创建输出目录
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    # 执行
    completed = 0
    ok_count = 0

    with open(args.output, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=M3_FIELDNAMES)
        writer.writeheader()

        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_task_wrapper, t): t for t in tasks}

            for future in as_completed(futures):
                completed += 1
                result = future.result()
                writer.writerow(result)

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
