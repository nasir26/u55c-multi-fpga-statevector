#!/bin/bash
# Compiles the exchange kernel (data type agnostic, moves 512 bit words) into builds/sv_xo/sv_swap.xo.
# Author: Nasir Ali, C-DAC Noida.
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/env.sh"; vitis_env
B=$MW/builds/sv_xo; cd $B
v++ -c -t hw --platform $PLATFORM -k sv_swap --hls.clock 300000000:sv_swap \
  --temp_dir $B/_xs --report_dir $B/reports_swap --log_dir $B/logs_swap -o $B/sv_swap.xo $MW/kernels/sv_swap.cpp
echo XO_OK
