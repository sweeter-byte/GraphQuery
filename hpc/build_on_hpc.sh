#!/usr/bin/bash
#
# 在超算上编译 SubgraphMatching.out（在 singularity 容器内执行）
#
# 用法（在超算 DIR 目录下）:
#   module load singularity
#   singularity exec ~/software/wzk-ubuntu2204-dev.sif bash hpc/build_on_hpc.sh
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SURVEY_DIR="$PROJECT_ROOT/core/engines/SubgraphMatchingSurvey/vlabel"

echo "=== Building SubgraphMatching.out ==="
echo "Survey dir: $SURVEY_DIR"

cd "$SURVEY_DIR"
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

echo ""
echo "=== Build complete ==="

# 验证二进制文件
BINARY="$SURVEY_DIR/build/matching/SubgraphMatching.out"
if [ -f "$BINARY" ]; then
    echo "Binary: $BINARY"
    echo "Checking dependencies..."
    ldd "$BINARY" || true
else
    echo "ERROR: Binary not found at $BINARY"
    exit 1
fi
