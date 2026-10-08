#!/bin/bash
# usage: link.sh <name> <xo_dir> <num_engines> [pcs_per_engine] [num_swap_CUs]
#   engine i -> HBM[i*W .. i*W+W-1], engines spread over SLR0..2; swap CUs: both ports HBM[0:31], SLR0.
#   The swap kernel object is the data type agnostic sv_swap.xo of the 30 qubit work (kernels/sv_swap.cpp, built by builds/sv_xo/build_swap.sh) (moves 512 bit words).
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/env.sh"; vitis_env
NAME=$1; XO=$MW/builds/$2/sv128_engine.xo; NE=$3; W=${4:-$((32/NE))}; NS=${5:-0}
B=$MW/builds/$NAME; mkdir -p $B; cd $B
{ echo "[connectivity]"; echo "nk=sv128_engine:$NE"
  for i in $(seq 1 $NE); do pc=$(( (i-1)*W )); if [ $W -gt 1 ]; then echo "sp=sv128_engine_$i.st:HBM[$pc:$((pc+W-1))]"; else echo "sp=sv128_engine_$i.st:HBM[$pc]"; fi
    echo "slr=sv128_engine_$i:SLR$(( (i-1) * 3 / NE ))"; done
  if [ $NS -gt 0 ]; then echo "nk=sv_swap:$NS"
    for i in $(seq 1 $NS); do echo "sp=sv_swap_$i.a:HBM[0:31]"; echo "sp=sv_swap_$i.b:HBM[0:31]"; echo "slr=sv_swap_$i:SLR0"; done; fi; } > link.cfg
XOS="$XO"; [ $NS -gt 0 ] && XOS="$XOS $MW/builds/sv_xo/sv_swap.xo"
v++ -l -t hw --platform $PLATFORM --config link.cfg --kernel_frequency 300 -j 16 \
  --temp_dir $B/_x --report_dir $B/reports --log_dir $B/logs -o $B/sv.xclbin $XOS
sha256sum sv.xclbin > sv.xclbin.sha256; echo BUILD_OK
