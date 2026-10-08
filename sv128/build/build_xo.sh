#!/bin/bash
# usage: build_xo.sh <name> [extra v++ -D flags ...]   e.g. build_xo.sh xo_w512 -D SV_WIDE
# Compiles the complex128 engine kernel into $MW/builds/<name>/sv128_engine.xo
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/env.sh"; vitis_env
NAME=$1; shift
B=$MW/builds/$NAME; mkdir -p $B; cd $B
SRC=$MW/sv128/kernels/sv128_engine.cpp
git -C $MW rev-parse HEAD > source_rev.txt; sha256sum $SRC >> source_rev.txt; echo "$@" > defines.txt
v++ -c -t hw --platform $PLATFORM -k sv128_engine "$@" --hls.clock 300000000:sv128_engine \
  --temp_dir $B/_x --report_dir $B/reports --log_dir $B/logs -o $B/sv128_engine.xo $SRC
echo XO_OK
