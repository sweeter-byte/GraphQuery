#!/usr/bin/bash
#
# 按数据集规模分配不同数量的 SLURM 作业，实现大图数据集的充分并行化。
#
# 每个数据集的查询任务按 (size, mode) 组合分片，分配到指定数量的节点上。
# 大数据集（patents, youtube, eu2005, wordnet）使用更多节点和更长的时间限制。
#
# 用法:
#   bash hpc/submit_m1_scaled.sh              # 提交全部数据集
#   bash hpc/submit_m1_scaled.sh patents      # 只提交 patents
#   bash hpc/submit_m1_scaled.sh --rerun-failed results/  # 重跑失败任务
#
# 环境变量覆盖:
#   TIME_LIMIT=180 bash hpc/submit_m1_scaled.sh   # 覆盖每查询超时 (秒)
#   DRY_RUN=1 bash hpc/submit_m1_scaled.sh        # 只打印命令不提交
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ---- 可调参数 ----
TIME_LIMIT="${TIME_LIMIT:-120}"
DRY_RUN="${DRY_RUN:-0}"

# ---- 查询图的所有 (size, mode) 组合 ----
SIZES=(4 8 10 12 14 16 20 24 32)
MODES=(dense sparse)

# 生成所有 pattern
ALL_PATTERNS=()
for size in "${SIZES[@]}"; do
    for mode in "${MODES[@]}"; do
        ALL_PATTERNS+=("${mode}_${size}")
    done
done
TOTAL_PATTERNS=${#ALL_PATTERNS[@]}  # 18 patterns

# ---- 每个数据集的节点(作业)数配置 ----
# 格式: dataset:num_jobs
# 每个作业处理若干 (size, mode) 分片
declare -A DATASET_JOBS
DATASET_JOBS=(
    [patents]=20
    [youtube]=10
    [eu2005]=10
    [wordnet]=5
    [human]=5
    [hprd]=2
    [dblp]=2
    [yeast]=1
)

# ---- 辅助函数 ----
submit_dataset() {
    local dataset="$1"
    local num_jobs="${DATASET_JOBS[$dataset]:-1}"

    echo ""
    echo "=== Dataset: $dataset (${num_jobs} jobs) ==="

    # 创建日志目录
    local log_dir="$PROJECT_ROOT/results/logs/${dataset}"
    mkdir -p "$log_dir"

    if [ "$num_jobs" -ge "$TOTAL_PATTERNS" ]; then
        # 每个 pattern 一个独立作业
        for pattern in "${ALL_PATTERNS[@]}"; do
            submit_one_job "$dataset" "$pattern" "$log_dir"
        done
    else
        # 将 patterns 均匀分配到 num_jobs 个作业中
        local patterns_per_job=$(( (TOTAL_PATTERNS + num_jobs - 1) / num_jobs ))
        local job_idx=0

        for (( i=0; i<TOTAL_PATTERNS; i+=patterns_per_job )); do
            local end=$(( i + patterns_per_job ))
            if [ "$end" -gt "$TOTAL_PATTERNS" ]; then
                end=$TOTAL_PATTERNS
            fi

            # 取该作业负责的 patterns
            local job_patterns=()
            for (( j=i; j<end; j++ )); do
                job_patterns+=("${ALL_PATTERNS[$j]}")
            done

            local patterns_str="${job_patterns[*]}"
            local first_pattern="${job_patterns[0]}"
            local last_pattern="${job_patterns[-1]}"
            local label="${first_pattern}..${last_pattern}"

            submit_batch_job "$dataset" "$patterns_str" "$label" "$log_dir" "$job_idx"
            job_idx=$((job_idx + 1))
        done
    fi
}

submit_one_job() {
    local dataset="$1"
    local pattern="$2"
    local log_dir="$3"

    local job_name="m1_${dataset}_${pattern}"
    local cmd="DATASETS=\"$dataset\" QUERY_PATTERN=\"$pattern\" TIME_LIMIT=\"$TIME_LIMIT\" \
sbatch --job-name=\"$job_name\" \
       --output=\"${log_dir}/${pattern}_%J.out\" \
       --error=\"${log_dir}/${pattern}_%J.err\" \
       \"$PROJECT_ROOT/hpc/submit_experiment.sh\""

    if [ "$DRY_RUN" = "1" ]; then
        echo "  [DRY_RUN] $cmd"
    else
        echo "  Submitting: $job_name"
        eval "$cmd"
    fi
}

submit_batch_job() {
    local dataset="$1"
    local patterns_str="$2"
    local label="$3"
    local log_dir="$4"
    local job_idx="$5"

    # 创建临时 wrapper 脚本，依次运行多个 pattern
    local wrapper="$log_dir/batch_${job_idx}.sh"
    cat > "$wrapper" << WRAPPER_EOF
#!/usr/bin/bash
#SBATCH -J m1_${dataset}_batch${job_idx}
#SBATCH -p cpu
#SBATCH -n 1
#SBATCH --cpus-per-task=16
#SBATCH --output=${log_dir}/batch${job_idx}_%J.out
#SBATCH --error=${log_dir}/batch${job_idx}_%J.err

set -uo pipefail

PROJECT_ROOT="$PROJECT_ROOT"
PYTHON="\${PYTHON:-\$PROJECT_ROOT/sc-graphquery-env/bin/python3}"
if [ ! -f "\$PYTHON" ]; then
    PYTHON="python3"
fi

SURVEY_BUILD="\$PROJECT_ROOT/core/engines/SubgraphMatchingSurvey/vlabel/build"
export LD_LIBRARY_PATH="\${SURVEY_BUILD}/graph:\${SURVEY_BUILD}/utility:\${SURVEY_BUILD}/utility/nucleus_decomposition:\${SURVEY_BUILD}/utility/execution_tree:\${LD_LIBRARY_PATH:-}"

module load singularity 2>/dev/null || true

PATTERNS=($patterns_str)
for pattern in "\${PATTERNS[@]}"; do
    OUTPUT_FILE="\$PROJECT_ROOT/results/m1_sequences_${dataset}_\${pattern}.csv"
    echo "[\$(date)] Running: dataset=$dataset pattern=\$pattern"
    \$PYTHON "\$PROJECT_ROOT/tools/run_filter_order_experiment.py" \\
        --dataset_dir "\$PROJECT_ROOT/dataset" \\
        --output "\$OUTPUT_FILE" \\
        --workers 16 \\
        --time_limit ${TIME_LIMIT} \\
        --datasets $dataset \\
        --query_pattern "\$pattern" || echo "WARNING: pattern \$pattern failed"
    echo "[\$(date)] Done: \$pattern"
done

echo "=== Batch job ${job_idx} complete ==="
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

# 处理 --rerun-failed 模式
if [ "${1:-}" = "--rerun-failed" ]; then
    RESULTS_DIR="${2:-$PROJECT_ROOT/results}"
    echo "=== Checking for failed/timeout tasks in $RESULTS_DIR ==="

    # 扫描 CSV 文件中的 TIMEOUT/CRASH/ERROR 行
    FAILED_FILE="$RESULTS_DIR/failed_tasks.txt"
    > "$FAILED_FILE"

    for csv in "$RESULTS_DIR"/m1_sequences*.csv; do
        [ -f "$csv" ] || continue
        # 提取失败行: dataset, query_pattern (从 query_file 推断)
        awk -F',' '
        NR > 1 && ($NF == "TIMEOUT" || $NF ~ /^CRASH/ || $NF ~ /^ERROR/) {
            # 从 query_file 提取 pattern (如 query_dense_8_42.graph -> dense_8)
            split($2, parts, "_")
            if (length(parts) >= 3) {
                pattern = parts[2] "_" parts[3]
            } else {
                pattern = "unknown"
            }
            print $1 "," pattern
        }
        ' "$csv" >> "$FAILED_FILE"
    done

    if [ ! -s "$FAILED_FILE" ]; then
        echo "No failed tasks found."
        rm -f "$FAILED_FILE"
        exit 0
    fi

    # 统计并去重
    echo ""
    echo "Failed task summary by (dataset, pattern):"
    sort "$FAILED_FILE" | uniq -c | sort -rn | head -50

    # 提取需要重跑的 (dataset, pattern) 组合
    RERUN_PAIRS=$(sort -u "$FAILED_FILE")
    echo ""
    echo "Unique (dataset, pattern) pairs to rerun: $(echo "$RERUN_PAIRS" | wc -l)"
    echo ""

    read -rp "Submit rerun jobs? [y/N] " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted. Failed tasks saved to: $FAILED_FILE"
        exit 0
    fi

    mkdir -p "$RESULTS_DIR/logs/rerun"

    echo "$RERUN_PAIRS" | while IFS=',' read -r dataset pattern; do
        dataset=$(echo "$dataset" | xargs)
        pattern=$(echo "$pattern" | xargs)
        [ -z "$dataset" ] || [ -z "$pattern" ] && continue

        local_output="$RESULTS_DIR/m1_sequences_rerun_${dataset}_${pattern}.csv"
        echo "  Rerunning: dataset=$dataset pattern=$pattern"

        if [ "$DRY_RUN" = "1" ]; then
            echo "    [DRY_RUN] sbatch ..."
        else
            DATASETS="$dataset" \
            QUERY_PATTERN="$pattern" \
            TIME_LIMIT="$TIME_LIMIT" \
            OUTPUT_DIR="$RESULTS_DIR" \
                sbatch --job-name="m1_rerun_${dataset}_${pattern}" \
                       --output="$RESULTS_DIR/logs/rerun/${dataset}_${pattern}_%J.out" \
                       --error="$RESULTS_DIR/logs/rerun/${dataset}_${pattern}_%J.err" \
                       "$PROJECT_ROOT/hpc/submit_experiment.sh"
        fi
    done

    echo ""
    echo "Rerun jobs submitted. Use 'squeue' to monitor."
    exit 0
fi

# ---- 正常提交模式 ----
echo "============================================"
echo " GraphQuery M1 Scaled Submission"
echo "============================================"
echo "  Per-query timeout : ${TIME_LIMIT}s"
echo "  Patterns per dataset: ${TOTAL_PATTERNS}"
echo "  Dry run            : ${DRY_RUN}"
echo ""
echo "  Dataset allocation:"
for ds in patents youtube eu2005 wordnet human hprd dblp yeast; do
    printf "    %-10s : %2d jobs\n" "$ds" "${DATASET_JOBS[$ds]:-1}"
done
echo "============================================"

mkdir -p "$PROJECT_ROOT/results/logs"

# 如果指定了数据集参数，只提交该数据集
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
echo "  After completion, run:"
echo "    bash hpc/merge_results.sh results/m1_sequences_*.csv -o results/m1_sequences_merged.csv"
echo "============================================"
