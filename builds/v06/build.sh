#!/bin/bash
# Rebuild of the submitted v06 kernel from Nasir's source, same flow as its steps log (v++ 2023.2, default 300 MHz
# target; the original closed at 258 MHz). Bindings from the original xclbin info: bank0..7 -> HBM[0..7], gate_sequence -> HBM[8].
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/env.sh"; vitis_env
B=$MW/builds/v06; cd $B
sha256sum quantum_fpga_kernel_complex128_v06.cpp > source_sha256.txt
v++ -c -t hw --platform $PLATFORM -k quantum_fpga_kernel_complex128 --temp_dir $B/_xc --report_dir $B/reports --log_dir $B/logs \
  -o quantum_fpga_kernel_complex128_v06.xo quantum_fpga_kernel_complex128_v06.cpp
v++ -l -t hw --platform $PLATFORM --config link.cfg -j 16 --temp_dir $B/_x --report_dir $B/reports --log_dir $B/logs \
  -o quantum_fpga_kernel_complex128_v06.xclbin quantum_fpga_kernel_complex128_v06.xo
sha256sum quantum_fpga_kernel_complex128_v06.xclbin > xclbin.sha256; echo BUILD_OK
