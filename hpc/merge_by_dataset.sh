#!/bin/bash
# ---------------------------------------------------------------------------
# Merge all m1_sequences_*.csv files by dataset.
#
# Usage:  cd <results_dir> && bash /path/to/merge_by_dataset.sh
#
# Output: order_data/<dataset>.csv  (one file per dataset, deduplicated)
# ---------------------------------------------------------------------------
set -euo pipefail

OUTDIR="order_data"
mkdir -p "$OUTDIR"

DATASETS=(dblp eu2005 hprd human patents wordnet yeast youtube)
HEADER="dataset,query_file,query_vertices,query_edges,filter,order,sequence,filter_time,plan_time,preprocessing_time,status"

total_files=0
total_rows=0

for ds in "${DATASETS[@]}"; do
    outfile="$OUTDIR/${ds}.csv"
    tmpfile=$(mktemp)

    file_count=0
    # Collect all CSV files for this dataset (base + dense/sparse variants)
    for f in m1_sequences_${ds}.csv m1_sequences_${ds}_*.csv; do
        [ -f "$f" ] || continue
        # Strip header, append data lines
        tail -n +2 "$f" >> "$tmpfile"
        file_count=$((file_count + 1))
    done

    if [ "$file_count" -eq 0 ]; then
        echo "SKIP: no files found for dataset '$ds'"
        rm -f "$tmpfile"
        continue
    fi

    # Deduplicate: same (dataset, query_file, filter, order) keeps first occurrence
    echo "$HEADER" > "$outfile"
    awk -F',' '!seen[$1","$2","$5","$6]++' "$tmpfile" >> "$outfile"

    data_rows=$(( $(wc -l < "$outfile") - 1 ))
    raw_rows=$(wc -l < "$tmpfile")
    dup_rows=$((raw_rows - data_rows))

    echo "OK: $outfile | $file_count files | $data_rows rows (removed $dup_rows duplicates)"
    total_files=$((total_files + file_count))
    total_rows=$((total_rows + data_rows))
    rm -f "$tmpfile"
done

echo "---"
echo "Done: $total_files files merged into ${#DATASETS[@]} datasets ($total_rows total rows) -> $OUTDIR/"
