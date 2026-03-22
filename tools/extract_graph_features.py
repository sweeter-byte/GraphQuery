#!/usr/bin/env python3
"""
补充脚本 A：提取查询图和数据图的静态结构特征。

从 .graph 文件直接解析，不需要运行 C++ 二进制。
输出两个 CSV 文件：
  - data_graph_features.csv   : 数据图特征
  - query_graph_features.csv  : 查询图特征

输出字段:
  数据图: dataset, data_vertices, data_edges, data_density,
          data_max_degree, data_avg_degree, data_label_count
  查询图: dataset, query_file, query_vertices, query_edges, query_density,
          query_max_degree, query_avg_degree, query_label_count,
          query_min_degree, query_degree_std

用法:
    python tools/extract_graph_features.py --dataset_dir dataset
    python tools/extract_graph_features.py --dataset_dir dataset --datasets yeast dblp
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# .graph 文件解析
# ---------------------------------------------------------------------------

def parse_graph_file(filepath: str) -> dict:
    """解析 .graph 文件，提取结构特征。

    格式:
        t <num_vertices> <num_edges>
        v <id> <label> <degree>
        e <src> <tgt> [<edge_label>]
    """
    num_vertices = 0
    num_edges = 0
    degrees: list[int] = []
    labels: set[int] = set()

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if parts[0] == "t":
                num_vertices = int(parts[1])
                num_edges = int(parts[2])
            elif parts[0] == "v":
                label = int(parts[2])
                degree = int(parts[3])
                degrees.append(degree)
                labels.add(label)

    if num_vertices == 0:
        return {
            "vertices": 0, "edges": 0, "density": 0.0,
            "max_degree": 0, "min_degree": 0,
            "avg_degree": 0.0, "degree_std": 0.0,
            "label_count": 0,
        }

    max_deg = max(degrees) if degrees else 0
    min_deg = min(degrees) if degrees else 0
    avg_deg = sum(degrees) / len(degrees) if degrees else 0.0
    # density = 2|E| / (|V| * (|V|-1)), 防止除零
    denom = num_vertices * (num_vertices - 1)
    density = (2 * num_edges / denom) if denom > 0 else 0.0
    # 标准差
    if len(degrees) > 1:
        variance = sum((d - avg_deg) ** 2 for d in degrees) / len(degrees)
        degree_std = math.sqrt(variance)
    else:
        degree_std = 0.0

    return {
        "vertices": num_vertices,
        "edges": num_edges,
        "density": round(density, 6),
        "max_degree": max_deg,
        "min_degree": min_deg,
        "avg_degree": round(avg_deg, 4),
        "degree_std": round(degree_std, 4),
        "label_count": len(labels),
    }


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
    # 优先使用 gen_query_graph，其次 query_graph
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

DATA_FIELDS = [
    "dataset", "data_vertices", "data_edges", "data_density",
    "data_max_degree", "data_avg_degree", "data_label_count",
]

QUERY_FIELDS = [
    "dataset", "query_file",
    "query_vertices", "query_edges", "query_density",
    "query_max_degree", "query_min_degree",
    "query_avg_degree", "query_degree_std",
    "query_label_count",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="补充脚本 A：提取查询图和数据图的静态结构特征"
    )
    parser.add_argument(
        "--dataset_dir", default=str(PROJECT_ROOT / "dataset"),
        help="数据集根目录 (default: <project>/dataset)",
    )
    parser.add_argument(
        "--output_dir", default=str(PROJECT_ROOT / "results"),
        help="输出目录",
    )
    parser.add_argument(
        "--datasets", nargs="*", default=None,
        help="只处理指定数据集 (默认全部)",
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

    os.makedirs(args.output_dir, exist_ok=True)

    data_csv_path = os.path.join(args.output_dir, "data_graph_features.csv")
    query_csv_path = os.path.join(args.output_dir, "query_graph_features.csv")

    # --- 数据图特征 ---
    print(f"Extracting data graph features...")
    with open(data_csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DATA_FIELDS)
        writer.writeheader()

        for dataset_name, data_graph_path in all_datasets:
            print(f"  {dataset_name}: {data_graph_path}")
            feat = parse_graph_file(data_graph_path)
            writer.writerow({
                "dataset": dataset_name,
                "data_vertices": feat["vertices"],
                "data_edges": feat["edges"],
                "data_density": feat["density"],
                "data_max_degree": feat["max_degree"],
                "data_avg_degree": feat["avg_degree"],
                "data_label_count": feat["label_count"],
            })

    print(f"  -> {data_csv_path}")

    # --- 查询图特征 ---
    print(f"\nExtracting query graph features...")
    total_queries = 0

    with open(query_csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=QUERY_FIELDS)
        writer.writeheader()

        for dataset_name, _ in all_datasets:
            queries = discover_queries(args.dataset_dir, dataset_name)
            print(f"  {dataset_name}: {len(queries)} query graphs")

            for qpath in queries:
                feat = parse_graph_file(qpath)
                writer.writerow({
                    "dataset": dataset_name,
                    "query_file": os.path.basename(qpath),
                    "query_vertices": feat["vertices"],
                    "query_edges": feat["edges"],
                    "query_density": feat["density"],
                    "query_max_degree": feat["max_degree"],
                    "query_min_degree": feat["min_degree"],
                    "query_avg_degree": feat["avg_degree"],
                    "query_degree_std": feat["degree_std"],
                    "query_label_count": feat["label_count"],
                })
                total_queries += 1

    print(f"  -> {query_csv_path}")
    print(f"\nDone: {len(all_datasets)} datasets, {total_queries} query graphs")


if __name__ == "__main__":
    main()
