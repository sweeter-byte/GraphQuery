#!/usr/bin/bash
#
# 合并多个分片结果 CSV 为一个完整的 CSV
#
# 用法:
#   bash hpc/merge_results.sh results/m1_sequences_*.csv -o results/m1_sequences.csv
#

set -euo pipefail

OUTPUT="results/m1_sequences_merged.csv"
INPUT_FILES=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -o|--output) OUTPUT="$2"; shift 2 ;;
        *) INPUT_FILES+=("$1"); shift ;;
    esac
done

if [ ${#INPUT_FILES[@]} -eq 0 ]; then
    echo "Usage: $0 results/m1_*.csv [-o output.csv]"
    exit 1
fi

echo "Merging ${#INPUT_FILES[@]} CSV files -> $OUTPUT"

# 取第一个文件的 header
head -1 "${INPUT_FILES[0]}" > "$OUTPUT"

# 追加所有文件的数据行 (跳过 header)
for f in "${INPUT_FILES[@]}"; do
    tail -n +2 "$f" >> "$OUTPUT"
done

TOTAL=$(tail -n +2 "$OUTPUT" | wc -l)
echo "Done. Total rows: $TOTAL"
echo "Output: $OUTPUT"
