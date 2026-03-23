#!/usr/bin/bash
#
# 按查询图大小 (size) 分片提交多个 SLURM 作业，进一步并行化。
#
# 用法:
#   bash hpc/submit_by_size.sh [dataset_name]
#
# 示例:
#   bash hpc/submit_by_size.sh yeast       # 只跑 yeast
#   bash hpc/submit_by_size.sh             # 跑所有数据集
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATASET="${1:-}"

# 查询图的所有 size
SIZES="2 3 4 5 6 7 8 9 10 11 12 13 14 16 20 24 28 32"
MODES="dense sparse"

for size in $SIZES; do
    for mode in $MODES; do
        pattern="${mode}_${size}"
        echo "Submitting job for pattern: $pattern (dataset: ${DATASET:-all})"

        DATASETS="$DATASET" \
        QUERY_PATTERN="$pattern" \
        OUTPUT_DIR="$PROJECT_ROOT/results" \
            sbatch --job-name="gq_${pattern}" \
                   --output="$PROJECT_ROOT/results/logs/${pattern}_%J.out" \
                   --error="$PROJECT_ROOT/results/logs/${pattern}_%J.err" \
                   "$PROJECT_ROOT/hpc/submit_experiment.sh"
    done
done

echo ""
echo "All jobs submitted. Use 'squeue' to monitor."
