#!/usr/bin/bash
#
# M3 引擎实验: 对每个数据集的 order_data CSV, 用 7 个兼容引擎执行真实枚举。
#
# 前置条件:
#   1. 已运行 merge_by_dataset.sh, 生成 order_data/<dataset>.csv
#   2. Survey 二进制已编译
#
# 用法:
#   bash hpc/submit_m3_scaled.sh              # 提交全部数据集
#   bash hpc/submit_m3_scaled.sh patents      # 只提交 patents
#   DRY_RUN=1 bash hpc/submit_m3_scaled.sh    # 只打印命令
#
# 环境变量:
#   TIME_LIMIT=60     每次枚举超时 (秒, 默认 60)
#   WORKERS=16        每个作业的并行进程数
#   DRY_RUN=1         只打印不提交
#   ORDER_DIR=...     order_data 目录 (默认 results/order_data)
#

set -euo pipefail

PROJECT_ROOT="/fs0/home/hpc70207290/ranmaoyin2025/GraphQuery"

# ---- 可调参数 ----
TIME_LIMIT="${TIME_LIMIT:-60}"
WORKERS="${WORKERS:-16}"
DRY_RUN="${DRY_RUN:-0}"
ORDER_DIR="${ORDER_DIR:-${PROJECT_ROOT}/results/order_data}"

# ---- 查询图的所有 (size, mode) 组合 ----
SIZES=(2 3 4 5 6 7 8 9 10 11 12 13 14 16 20 24 28 32)
MODES=(dense sparse)

ALL_PATTERNS=()
for size in "${SIZES[@]}"; do
    for mode in "${MODES[@]}"; do
        ALL_PATTERNS+=("${mode}_${size}")
    done
done
TOTAL_PATTERNS=${#ALL_PATTERNS[@]}

# ---- 每个数据集的作业数配置 ----
# M3 比 M1 计算量大 (真实枚举), 分配更多节点
declare -A DATASET_JOBS
DATASET_JOBS=(
    [patents]=36
    [youtube]=20
    [eu2005]=20
    [wordnet]=10
    [human]=10
    [hprd]=5
    [dblp]=5
    [yeast]=2
)

# ---- 辅助函数 ----
submit_dataset() {
    local dataset="$1"
    local num_jobs="${DATASET_JOBS[$dataset]:-1}"
    local order_csv="${ORDER_DIR}/${dataset}.csv"

    if [ ! -f "$order_csv" ]; then
        echo "  SKIP: order CSV not found: $order_csv"
        return
    fi

    echo ""
    echo "=== Dataset: $dataset (${num_jobs} jobs) ==="

    local log_dir="$PROJECT_ROOT/results/logs/m3_${dataset}"
    mkdir -p "$log_dir"

    if [ "$num_jobs" -ge "$TOTAL_PATTERNS" ]; then
        # 每个 pattern 一个作业
        for pattern in "${ALL_PATTERNS[@]}"; do
            submit_one_job "$dataset" "$pattern" "$log_dir" "$order_csv"
        done
    else
        # 均匀分片
        local patterns_per_job=$(( (TOTAL_PATTERNS + num_jobs - 1) / num_jobs ))
        local job_idx=0

        for (( i=0; i<TOTAL_PATTERNS; i+=patterns_per_job )); do
            local end=$(( i + patterns_per_job ))
            [ "$end" -gt "$TOTAL_PATTERNS" ] && end=$TOTAL_PATTERNS

            local job_patterns=()
            for (( j=i; j<end; j++ )); do
                job_patterns+=("${ALL_PATTERNS[$j]}")
            done

            local patterns_str="${job_patterns[*]}"
            local label="${job_patterns[0]}..${job_patterns[-1]}"

            submit_batch_job "$dataset" "$patterns_str" "$label" "$log_dir" "$job_idx" "$order_csv"
            job_idx=$((job_idx + 1))
        done
    fi
}

submit_one_job() {
    local dataset="$1"
    local pattern="$2"
    local log_dir="$3"
    local order_csv="$4"

    local job_name="m3_${dataset}_${pattern}"
    local output_file="$PROJECT_ROOT/results/m3_engines_${dataset}_${pattern}.csv"

    local wrapper="$log_dir/job_${pattern}.sh"
    cat > "$wrapper" << WRAPPER_EOF
#!/usr/bin/bash
#SBATCH -J ${job_name}
#SBATCH -p cpu
#SBATCH -n 1
#SBATCH --cpus-per-task=${WORKERS}
#SBATCH --output=${log_dir}/${pattern}_%J.out
#SBATCH --error=${log_dir}/${pattern}_%J.err

set -uo pipefail

PROJECT_ROOT="$PROJECT_ROOT"
PYTHON="python3"

SURVEY_BUILD="\$PROJECT_ROOT/core/engines/SubgraphMatchingSurvey/vlabel/build"
export LD_LIBRARY_PATH="\${SURVEY_BUILD}/graph:\${SURVEY_BUILD}/utility:\${SURVEY_BUILD}/utility/nucleus_decomposition:\${SURVEY_BUILD}/utility/execution_tree:\${LD_LIBRARY_PATH:-}"

module load gcc/9.3.0 2>/dev/null || true
module load python/3.8.3 2>/dev/null || true

echo "[\$(date)] Running M3: dataset=${dataset} pattern=${pattern}"
\$PYTHON "\$PROJECT_ROOT/tools/run_m3_engine_experiment.py" \\
    --dataset_dir "\$PROJECT_ROOT/dataset" \\
    --order_csv "${order_csv}" \\
    --output "${output_file}" \\
    --workers ${WORKERS} \\
    --time_limit ${TIME_LIMIT} \\
    --query_pattern "${pattern}" || echo "WARNING: ${pattern} failed"
echo "[\$(date)] Done: ${pattern}"
WRAPPER_EOF
    chmod +x "$wrapper"

    if [ "$DRY_RUN" = "1" ]; then
        echo "  [DRY_RUN] sbatch $wrapper"
    else
        echo "  Submitting: $job_name"
        sbatch "$wrapper"
    fi
}

submit_batch_job() {
    local dataset="$1"
    local patterns_str="$2"
    local label="$3"
    local log_dir="$4"
    local job_idx="$5"
    local order_csv="$6"

    local wrapper="$log_dir/batch_${job_idx}.sh"
    cat > "$wrapper" << WRAPPER_EOF
#!/usr/bin/bash
#SBATCH -J m3_${dataset}_batch${job_idx}
#SBATCH -p cpu
#SBATCH -n 1
#SBATCH --cpus-per-task=${WORKERS}
#SBATCH --output=${log_dir}/batch${job_idx}_%J.out
#SBATCH --error=${log_dir}/batch${job_idx}_%J.err

set -uo pipefail

PROJECT_ROOT="$PROJECT_ROOT"
PYTHON="python3"

SURVEY_BUILD="\$PROJECT_ROOT/core/engines/SubgraphMatchingSurvey/vlabel/build"
export LD_LIBRARY_PATH="\${SURVEY_BUILD}/graph:\${SURVEY_BUILD}/utility:\${SURVEY_BUILD}/utility/nucleus_decomposition:\${SURVEY_BUILD}/utility/execution_tree:\${LD_LIBRARY_PATH:-}"

module load gcc/9.3.0 2>/dev/null || true
module load python/3.8.3 2>/dev/null || true

PATTERNS=($patterns_str)
for pattern in "\${PATTERNS[@]}"; do
    OUTPUT_FILE="\$PROJECT_ROOT/results/m3_engines_${dataset}_\${pattern}.csv"
    echo "[\$(date)] Running M3: dataset=${dataset} pattern=\$pattern"
    \$PYTHON "\$PROJECT_ROOT/tools/run_m3_engine_experiment.py" \\
        --dataset_dir "\$PROJECT_ROOT/dataset" \\
        --order_csv "${order_csv}" \\
        --output "\$OUTPUT_FILE" \\
        --workers ${WORKERS} \\
        --time_limit ${TIME_LIMIT} \\
        --query_pattern "\$pattern" || echo "WARNING: \$pattern failed"
    echo "[\$(date)] Done: \$pattern"
done

echo "=== M3 batch ${job_idx} complete ==="
WRAPPER_EOF
    chmod +x "$wrapper"

    if [ "$DRY_RUN" = "1" ]; then
        echo "  [DRY_RUN] sbatch $wrapper  (patterns: $label)"
    else
        echo "  Submitting batch ${job_idx}: $label"
        sbatch "$wrapper"
    fi
}

# ---- 主逻辑 ----
echo "============================================"
echo " GraphQuery M3 Engine Experiment Submission"
echo "============================================"
echo "  Per-enum timeout : ${TIME_LIMIT}s"
echo "  Workers per job  : ${WORKERS}"
echo "  Order data dir   : ${ORDER_DIR}"
echo "  Patterns per ds  : ${TOTAL_PATTERNS}"
echo "  Dry run          : ${DRY_RUN}"
echo ""
echo "  Dataset allocation:"
for ds in patents youtube eu2005 wordnet human hprd dblp yeast; do
    printf "    %-10s : %2d jobs\n" "$ds" "${DATASET_JOBS[$ds]:-1}"
done
echo "============================================"

mkdir -p "$PROJECT_ROOT/results/logs"

if [ -n "${1:-}" ]; then
    SELECTED_DATASETS=("$@")
else
    SELECTED_DATASETS=(patents youtube eu2005 wordnet human hprd dblp yeast)
fi

TOTAL_JOBS=0
for dataset in "${SELECTED_DATASETS[@]}"; do
    if [ -z "${DATASET_JOBS[$dataset]+x}" ]; then
        echo "WARNING: Unknown dataset '$dataset', skipping."
        continue
    fi
    submit_dataset "$dataset"
    TOTAL_JOBS=$((TOTAL_JOBS + ${DATASET_JOBS[$dataset]:-1}))
done

echo ""
echo "============================================"
echo "  Total jobs submitted: ~${TOTAL_JOBS}"
echo "  Use 'squeue -u \$USER' to monitor."
echo "  Output: results/m3_engines_<dataset>_<pattern>.csv"
echo "============================================"
