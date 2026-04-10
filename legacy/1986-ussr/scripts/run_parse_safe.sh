#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Conservative mode for throttled VPS:
# - bind to two CPUs with aggregate self-throttle
# - lowest CPU / IO priority
# - single-threaded OCR children
# - parser self-throttles below ~1.3 cores total
export OMP_THREAD_LIMIT=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

exec ionice -c 3 nice -n 19 taskset -c 0,1 \
  python3 parse_auto_run_tables.py --cpu-limit 1.30 "$@"
