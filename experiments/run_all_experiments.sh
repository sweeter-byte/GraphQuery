#!/usr/bin/env bash
# =============================================================================
# run_all_experiments.sh — 一键运行全部实验 (E1-E10)
#
# 数据集：yeast, wordnet, dblp（有 C++ 索引）
# Phase 1 额外包含：human, youtube, patents（纯 M1，无需索引）
#
# 用法：
#   conda activate fastest
#   bash experiments/run_all_experiments.sh
#
# 可选参数：
#   NUM_QUERIES=20 bash experiments/run_all_experiments.sh
#   SKIP_PHASE3=1  bash experiments/run_all_experiments.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# --- 可配置参数 ---
NUM_QUERIES="${NUM_QUERIES:-50}"
SEED="${SEED:-42}"
OUTPUT_DIR="${OUTPUT_DIR:-experiments/results}"
SKIP_PHASE1="${SKIP_PHASE1:-0}"
SKIP_PHASE2="${SKIP_PHASE2:-0}"
SKIP_PHASE3="${SKIP_PHASE3:-0}"

# 有 C++ 索引的数据集
DS_WITH_INDEX="yeast wordnet dblp"
# 全部数据集（Phase 1 用）
DS_ALL="yeast wordnet dblp human youtube patents"

mkdir -p "$OUTPUT_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# =============================================================================
# Phase 1: 纯 M1，无需 C++ 索引，秒级
# =============================================================================
if [ "$SKIP_PHASE1" = "0" ]; then
    log "========== Phase 1: M1 experiments (all 6 datasets) =========="

    log "E7a: search space reduction (--no-m2)..."
    python experiments/run_e7.py \
        --datasets $DS_ALL --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR" --no-m2

    log "E7c: ablation study..."
    python experiments/run_e7c.py \
        --datasets $DS_ALL --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "E7d: cost_factor sensitivity..."
    python experiments/run_e7d.py \
        --datasets $DS_ALL --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "Phase 1 complete."
else
    log "Phase 1 skipped (SKIP_PHASE1=1)."
fi

# =============================================================================
# Phase 2: M2 估计，需要 C++ 索引，分钟级
# =============================================================================
if [ "$SKIP_PHASE2" = "0" ]; then
    log "========== Phase 2: M2 experiments (yeast/wordnet/dblp) =========="

    log "E7 full (E7a+E7b+E7e with M2)..."
    python experiments/run_e7.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "E8: prefix deduplication (R1/R4 ablation + 4-pipeline)..."
    python experiments/run_e8.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "E8d: prefix sharing analysis..."
    python experiments/run_e8d.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "E9: R3 early stopping + R3/R4 synergy..."
    python experiments/run_e9.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "E9c: min_completed sensitivity..."
    python experiments/run_e9c.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "E10a: weighted cost model grid search..."
    python experiments/run_e10.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR" --grid-only

    log "E4: overhead reduction (beam width + R3 configs)..."
    python experiments/run_e4.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "Phase 2 complete."
else
    log "Phase 2 skipped (SKIP_PHASE2=1)."
fi

# =============================================================================
# Phase 3: M3 执行，需要 Survey 二进制，小时级
# =============================================================================
if [ "$SKIP_PHASE3" = "0" ]; then
    log "========== Phase 3: M3 experiments (yeast/wordnet/dblp) =========="

    log "E1: sequence quality (OPT vs RAND vs DEFAULT vs WORST)..."
    python experiments/run_e1.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "E2: estimation precision..."
    python experiments/run_e2.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "E3+E5+E6: end-to-end benefits..."
    python experiments/run_e3.py \
        --datasets $DS_WITH_INDEX --num-queries "$NUM_QUERIES" --seed "$SEED" \
        --output-dir "$OUTPUT_DIR"

    log "Phase 3 complete."
else
    log "Phase 3 skipped (SKIP_PHASE3=1)."
fi

# =============================================================================
log "========== All experiments complete =========="
log "Results in: $OUTPUT_DIR/"
ls -lh "$OUTPUT_DIR"/*.csv 2>/dev/null | awk '{print "  " $NF " (" $5 ")"}'
