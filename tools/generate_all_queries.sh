#!/usr/bin/env bash
#
# 为 dataset/ 下所有数据集批量生成查询图。
#
# 假设目录结构:
#   dataset/<name>/<name>.graph        (数据图)
#   dataset/<name>/query_graph/        (查询图输出目录)
#
# 用法:
#   bash tools/generate_all_queries.sh
#
# 可通过环境变量覆盖默认参数:
#   SIZES="8 12 16 24 32"  COUNT=200  SEED=42  bash tools/generate_all_queries.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GENERATOR="$PROJECT_ROOT/tools/query_graph_generator.py"
DATASET_DIR="$PROJECT_ROOT/dataset"

# ---- 可调参数 ----
# 18 * 2 * 200 = 7200 * 8 = 57600
SIZES="${SIZES:-2 3 4 5 6 7 8 9 10 11 12 13 14 16 20 24 28 32}" # 删除了16 20 24 32
MODES="${MODES:-dense sparse}"
COUNT="${COUNT:-200}"
SEED="${SEED:-42}"

echo "============================================"
echo " Batch Query Graph Generator"
echo "============================================"
echo "  Dataset dir : $DATASET_DIR"
echo "  Sizes       : $SIZES"
echo "  Modes       : $MODES"
echo "  Count/combo : $COUNT"
echo "  Seed        : $SEED"
echo "============================================"

found=0
for data_graph in "$DATASET_DIR"/*/; do
    name="$(basename "$data_graph")"
    graph_file="$data_graph/${name}.graph"

    if [ ! -f "$graph_file" ]; then
        echo "[SKIP] $name: $graph_file not found"
        continue
    fi

    output_dir="$data_graph/gen_query_graph"
    mkdir -p "$output_dir"

    echo ""
    echo ">>> Generating queries for: $name"
    echo "    Data graph: $graph_file"
    echo "    Output dir: $output_dir"

    python3 "$GENERATOR" \
        --data_graph "$graph_file" \
        --output_dir "$output_dir" \
        --sizes $SIZES \
        --modes $MODES \
        --count "$COUNT" \
        --seed "$SEED"

    found=$((found + 1))
done

echo ""
echo "============================================"
echo " Done. Processed $found dataset(s)."
echo "============================================"
