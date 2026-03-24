#!/usr/bin/bash
#SBATCH -J simulate
#SBATCH -p cpu
#SBATCH -n 1
#SBATCH --cpus-per-task=16
#SBATCH --error=%J.err
#SBATCH --output=%J.out
#
# 在超算上运行 filter-order 实验
#
# 用法:
#   # 方式1: 跑所有数据集
#   sbatch hpc/submit_experiment.sh
#
#   # 方式2: 只跑特定数据集
#   DATASETS="yeast" sbatch hpc/submit_experiment.sh
#
#   # 方式3: 只跑特定查询模式
#   DATASETS="yeast" QUERY_PATTERN="dense_8" sbatch hpc/submit_experiment.sh
#
#   # 方式4: 用 job array 按数据集并行 (假设有8个数据集)
#   sbatch --array=0-7 hpc/submit_experiment.sh
#

set -euo pipefail

# ---- 项目路径 (根据你的超算工作目录修改) ----
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ---- 可调参数 ----
WORKERS="${WORKERS:-16}"
TIME_LIMIT="${TIME_LIMIT:-120}"
DATASETS="${DATASETS:-}"
QUERY_PATTERN="${QUERY_PATTERN:-}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_ROOT/results}"

# ---- conda 虚拟环境路径 (根据你的实际路径修改) ----
PYTHON="${PYTHON:-$PROJECT_ROOT/sc-graphquery-env/bin/python3}"

# ---- 如果没有指定 PYTHON, 尝试系统 python3 ----
if [ ! -f "$PYTHON" ]; then
    PYTHON="python3"
fi

# ---- 设置 LD_LIBRARY_PATH ----
SURVEY_BUILD="$PROJECT_ROOT/core/engines/SubgraphMatchingSurvey/vlabel/build"
export LD_LIBRARY_PATH="${SURVEY_BUILD}/graph:${SURVEY_BUILD}/utility:${SURVEY_BUILD}/utility/nucleus_decomposition:${SURVEY_BUILD}/utility/execution_tree:${LD_LIBRARY_PATH:-}"

# ---- Job Array 支持: 按数据集分片 ----
ALL_DATASET_NAMES=(yeast hprd human wordnet dblp youtube eu2005 patents)

if [ -n "${SLURM_ARRAY_TASK_ID:-}" ]; then
    # Job array 模式: 每个 task 跑一个数据集
    IDX=$SLURM_ARRAY_TASK_ID
    if [ "$IDX" -ge "${#ALL_DATASET_NAMES[@]}" ]; then
        echo "SLURM_ARRAY_TASK_ID=$IDX exceeds dataset count, exiting."
        exit 0
    fi
    DATASETS="${ALL_DATASET_NAMES[$IDX]}"
    echo "Job array mode: task $IDX -> dataset $DATASETS"
fi

# ---- 构建命令 ----
OUTPUT_FILE="$OUTPUT_DIR/m1_sequences"
if [ -n "$DATASETS" ]; then
    OUTPUT_FILE="${OUTPUT_FILE}_${DATASETS}"
fi
OUTPUT_FILE="${OUTPUT_FILE}.csv"

mkdir -p "$OUTPUT_DIR"

CMD="$PYTHON $PROJECT_ROOT/tools/run_filter_order_experiment.py \
    --dataset_dir $PROJECT_ROOT/dataset \
    --output $OUTPUT_FILE \
    --workers $WORKERS \
    --time_limit $TIME_LIMIT"

if [ -n "$DATASETS" ]; then
    CMD="$CMD --datasets $DATASETS"
fi

if [ -n "$QUERY_PATTERN" ]; then
    CMD="$CMD --query_pattern $QUERY_PATTERN"
fi

echo "============================================"
echo " GraphQuery Filter-Order Experiment (HPC)"
echo "============================================"
echo "  Project root : $PROJECT_ROOT"
echo "  Python       : $PYTHON"
echo "  Workers      : $WORKERS"
echo "  Time limit   : $TIME_LIMIT"
echo "  Datasets     : ${DATASETS:-all}"
echo "  Query pattern: ${QUERY_PATTERN:-all}"
echo "  Output       : $OUTPUT_FILE"
echo "============================================"

# ---- 加载 singularity 并执行 ----
module load singularity 2>/dev/null || true

# 如果需要通过 singularity 运行 (glibc 兼容性)，取消注释下面一行并注释掉直接执行:
singularity exec --env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" ~/software/wzk-ubuntu2204-dev.sif $CMD

# 直接执行 (如果环境兼容):
echo "Running: $CMD"
eval $CMD

echo ""
echo "=== Experiment finished ==="
echo "Output: $OUTPUT_FILE"
