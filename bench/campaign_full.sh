#!/bin/bash
# Complete measurement campaign of the multi card revision on any host with four U55C cards (one stage list, no
# day/night split). Every engine configuration waits until all cards are below ${COOL:-84} C (parked on the small
# bitstream) and stops at 90 C (FPGA) or 85 C (HBM); stops are logged and reported as thermal limits.
# Grover runs only where its oracle is native on the engine (n <= 14 on one and two cards, n <= 16 on four cards).
# Card addresses: QSIM_BDFS (four cards), QSIM_CARDS1 (one card), QSIM_CARDS2 (two cards).
# Author: Nasir Ali, C-DAC Noida.
# usage: campaign_full.sh <engine xclbin> <engines per card> <v06 xclbin> [stage...]
#   stages (default all, in this order):
#     soak validate main scaling ablation part shor haar energy micro host baseline diagabl cpu
set -u
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/env.sh"
X=$(readlink -f $1); NE=$2; V06=$(readlink -f $3); shift 3
: "${QSIM_BDFS:?set QSIM_BDFS to the four card user functions, e.g. 0000:3b:00.1,...}"
: "${QSIM_CARDS1:?set QSIM_CARDS1 (one card)}"; : "${QSIM_CARDS2:?set QSIM_CARDS2 (two cards)}"
export QSIM_BDFS QSIM_CARDS1 QSIM_CARDS2
cd $MW
R=$MW/results/raw; L=$MW/logs; mkdir -p $R $L
log() { echo "[$(date -Is)] $*" | tee -a $L/campaign.log; }
eng() { local st=$1 out=$2; shift 2; mkdir -p $R/$st
  $PY_FPGA -u bench/run_engine.py --xclbin $X --engines $NE --swaps 4 --cool-c ${COOL:-84} --park-xclbin $V06 \
      --out $R/$st/$out.json "$@" >> $L/campaign_$st.log 2>&1
  log "$st/$out exit $?"; }
bl() { local out=$1; shift; mkdir -p $R/baseline
  $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --out $R/baseline/$out.json "$@" >> $L/campaign_baseline.log 2>&1
  log "baseline/$out exit $?"; }
busy=$(pgrep -fc 'vivado|v\+\+|vitis_hls' || true); [ "$busy" != "0" ] && { log "host not idle"; exit 2; }
log "campaign_full on $(hostname): cards $QSIM_BDFS, one card $QSIM_CARDS1, two cards $QSIM_CARDS2"
STAGES=${@:-soak validate main scaling ablation part shor haar energy micro host baseline diagabl cpu}
for s in $STAGES; do log "stage $s start"
  case $s in
  soak)      mkdir -p $R/thermal
             $PY_FPGA -u bench/thermal_soak.py --xclbin $X --park-xclbin $V06 --engines $NE --swaps 4 \
                 --idle-min ${SOAK_IDLE:-10} --load-min ${SOAK_LOAD:-15} --out $R/thermal/soak.json >> $L/campaign_thermal.log 2>&1
             log "thermal soak exit $?" ;;
  validate)  eng validation maxwidth_1card --cards 1 --circuits ghz,qft --ns 24,28,29 --reps 2
             eng validation maxwidth_2cards --cards 2 --circuits ghz,qft --ns 20,24,26,28,29,30 --reps 2
             eng validation maxwidth_4cards --cards 4 --circuits ghz,qft,rand10 --ns 24,28,30,31 --reps 2 ;;
  main)      eng main small_4c --cards 4 --circuits qft,ghz,bell,qft_iqft,rand10,partition_heavy --ns 4,6,8,10,12,14,16,18,20,22 --reps 11
             eng main grover_4c --cards 4 --circuits grover --ns 4,6,8,10,12,14,16 --reps 6
             eng main large_4c --cards 4 --circuits qft,ghz,rand10,qft_iqft --ns 24,26,28 --reps 6
             eng main max_4c --cards 4 --circuits ghz,qft,rand10 --ns 29,30,31 --reps 4 ;;
  scaling)   for c in 1 2 4; do eng scaling strong_${c}c --cards $c --circuits qft,ghz,rand10 --ns 20,22,24,26,28 --reps 6; done
             eng scaling weak_1c --cards 1 --circuits qft,rand10 --ns 26,27 --reps 4
             eng scaling weak_2c --cards 2 --circuits qft,rand10 --ns 27,28 --reps 4
             eng scaling weak_4c --cards 4 --circuits qft,rand10 --ns 28,29 --reps 4 ;;
  ablation)  for c in 2 4; do
               eng ablation flags_${c}c --cards $c --circuits qft,ghz,rand10,partition_heavy --ns 16,20,24,28 \
                   --flags 111a,011a,101a,110a,1110,0000 --reps 6
               eng ablation flags_grover_${c}c --cards $c --circuits grover --ns 8,12,14 --flags 111a,011a,101a,110a,1110,0000 --reps 6
               eng ablation ghz_variants_${c}c --cards $c --circuits ghz,ghz_top,ghz_log --ns 16,20,24,28 --flags 1110,1111 --reps 6
             done ;;
  part)      for c in 2 4; do
               eng part default_${c}c --cards $c --circuits qft,ghz --ns 16,20,24 --reps 6
               eng part low01_${c}c --cards $c --circuits qft,ghz --ns 16,20,24 --reps 6 --part 0,1
               eng part default_grover_${c}c --cards $c --circuits grover --ns 8,12,14 --reps 6
               eng part low01_grover_${c}c --cards $c --circuits grover --ns 8,12,14 --reps 6 --part 0,1
             done ;;
  shor)      for c in 2 4; do
               eng shor shor15_${c}c --cards $c --circuits shor15 --ns 12,16,20,24 --reps 6
               eng shor qpe_${c}c --cards $c --circuits qpe --ns 12,16,20,24,28 --reps 6
             done ;;
  haar)      eng haar haar_4c --cards 4 --init haar --circuits qft,rand10,partition_heavy,ghz --ns 8,12,16,20,24,28 --reps 3 ;;
  energy)    for c in 1 2 4; do eng energy loop_${c}c --cards $c --power --circuits qft,rand10 --ns 26,28 --reps 12; done ;;
  micro)     mkdir -p $R/micro
             $PY_FPGA -u bench/micro_engine.py --xclbin $X --cards 4 --engines $NE --swaps 4 --out $R/micro/engine_4c.json >> $L/campaign_micro.log 2>&1
             log "micro engine exit $?"
             $PY_FPGA -c "import uuid, os, pyxrt; [pyxrt.device(b).load_xclbin('$V06') for b in os.environ['QSIM_BDFS'].split(',')]"
             $PY_FPGA -u baseline/micro_baseline.py $V06 4 26 $R/micro/baseline_v06_4c.json >> $L/campaign_micro.log 2>&1
             log "micro baseline exit $?" ;;
  host)      mkdir -p $R/host
             for nc in 4 8 16 64 256; do
               for c in 2 4; do
                 $PY_FPGA -u bench/run_engine.py --xclbin $X --engines $NE --swaps 4 --cool-c ${COOL:-84} --park-xclbin $V06 --cards $c \
                    --circuits qft,rand10 --ns 20,24 --reps 6 --out $R/host/engine${c}c_cores${nc}.json --pin-cores $nc >> $L/campaign_host.log 2>&1
                 log "host engine${c}c cores $nc exit $?"
               done
               $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --circuits qft --ns 16,20 --reps 4 --pin-cores $nc \
                  --out $R/host/baseline4c_cores${nc}.json >> $L/campaign_host.log 2>&1
               log "host baseline4c cores $nc exit $?"
             done ;;
  baseline)  bl v06_batched --circuits qft,ghz,bell,qft_iqft,rand10,partition_heavy --ns 4,8,12,14,16,18,20,22 --reps 6
             bl v06_pergate --per-gate --circuits qft,ghz,bell,qft_iqft,rand10,partition_heavy --ns 4,8,12,14,16,18,20 --reps 6
             bl v06_grover --circuits grover --ns 4,6,8,10,12 --reps 3
             bl v06_haar --init haar --circuits qft,rand10,partition_heavy --ns 8,12,16,20 --reps 3
             bl v06_large --circuits qft,ghz --ns 24,26,28 --reps 3 ;;
  diagabl)   bl v06_diag_on  --circuits qft --ns 8,12,16,18,20 --reps 4
             bl v06_diag_off --circuits qft --ns 8,12,16,18,20 --reps 4 --no-diag ;;
  cpu)       mkdir -p $R/cpu   # no card is used; run last so that no CPU load overlaps a timed FPGA run
             $PY_FPGA -u bench/run_qiskit_cpu.py --circuits qft,ghz,rand10,qft_iqft --ns 12,16,20,22,24,26,28,30 --reps 6 \
                 --out $R/cpu/qiskit_cpu.json >> $L/campaign_cpu.log 2>&1; log "cpu exit $?"
             $PY_FPGA -u bench/run_qiskit_cpu.py --circuits grover --ns 4,6,8,10,12 --reps 6 \
                 --out $R/cpu/qiskit_cpu_grover.json >> $L/campaign_cpu.log 2>&1; log "cpu grover exit $?"
             $PY_FPGA -u bench/run_qiskit_cpu.py --circuits grover --ns 14,16 --backends aer,aer1 --reps 6 \
                 --out $R/cpu/qiskit_cpu_grover_large.json >> $L/campaign_cpu.log 2>&1; log "cpu grover large exit $?" ;;
  *)         log "unknown stage $s" ;;
  esac
  log "stage $s end"
done
log "CAMPAIGN_FULL_DONE"
