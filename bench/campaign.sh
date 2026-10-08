#!/bin/bash
# Measurement campaign of the revision (run on an otherwise idle host, inside tmux).
# Author: Nasir Ali, C-DAC Noida.
# usage: campaign.sh <engine xclbin> <engines per card> <v06 xclbin> <stage...>
#   stages: main scaling ablation part shor haar energy micro baseline cpu   (default: all, in this order)
# Every stage writes JSON to $MW/results/raw/<stage>/ and logs to $MW/logs/campaign_<stage>.log.
set -u
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/env.sh"
X=$(readlink -f $1); NE=$2; V06=$(readlink -f $3); shift 3
STAGES=${@:-main scaling ablation part shor haar host energy micro baseline}
cd $MW
R=$MW/results/raw; L=$MW/logs
B="0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1"
log() { echo "[$(date -Is)] $*" | tee -a $L/campaign.log; }
idle() {
  local busy=$(pgrep -fc 'vivado|v\+\+|vitis_hls|cpu_bench|campaign_extra' || true)
  log "load $(cat /proc/loadavg) busy_tools=$busy"
  if [ "$busy" != "0" ]; then log "host not idle, stage $1 not started"; exit 2; fi
}
eng() { local st=$1 out=$2; shift 2; mkdir -p $R/$st
  $PY_FPGA -u bench/run_engine.py --xclbin $X --engines $NE --swaps 4 --cool-c ${COOL:-84} --out $R/$st/$out.json "$@" >> $L/campaign_$st.log 2>&1
  log "$st/$out exit $?"; }
for s in $STAGES; do
  idle $s; log "stage $s start"
  case $s in
  main)      # E1, E2, E3 on four cards: correctness at every width, timing and breakdown
    eng main small_4c --cards 4 --circuits qft,ghz,bell,qft_iqft,rand10,partition_heavy --ns 4,6,8,10,12,14,16,18,20,22 --reps 11
    eng main grover_4c --cards 4 --circuits grover --ns 4,6,8,10,12,14,16 --reps 6
    eng main large_4c --cards 4 --circuits qft,ghz,rand10,qft_iqft --ns 24,26,28 --reps 6
    eng main max_4c --cards 4 --circuits ghz,qft,rand10 --ns 29,30,31 --reps 4 ;;
  scaling)   # E4: strong scaling on 1, 2, 4 cards (same widths), weak scaling n = n0 + log2(cards)
    for c in 1 2 4; do
      eng scaling strong_${c}c --cards $c --circuits qft,ghz,rand10 --ns 20,22,24,26,28 --reps 6
    done
    eng scaling weak_1c --cards 1 --circuits qft,rand10 --ns 26,27 --reps 4
    eng scaling weak_2c --cards 2 --circuits qft,rand10 --ns 27,28 --reps 4
    eng scaling weak_4c --cards 4 --circuits qft,rand10 --ns 28,29 --reps 4 ;;
  ablation)  # E5, E6, R2.3: slice paths off one at a time, all off; GHZ variants; worst case circuit
    eng ablation flags_4c --cards 4 --circuits qft,ghz,rand10,partition_heavy,grover --ns 16,20,24,28 \
        --flags 111a,011a,101a,110a,1110,0000 --reps 6
    eng ablation ghz_variants_4c --cards 4 --circuits ghz,ghz_top,ghz_log --ns 16,20,24,28 --flags 1110,1111 --reps 6 ;;
  part)      # E10: partition qubit choice
    eng part default_4c --cards 4 --circuits qft,ghz,grover --ns 16,20,24 --reps 6
    eng part low01_4c --cards 4 --circuits qft,ghz,grover --ns 16,20,24 --reps 6 --part 0,1 ;;
  shor)      # E14: Shor QPE 7^x mod 15 with growing counting register, scalable phase QPE
    eng shor shor15_4c --cards 4 --circuits shor15 --ns 9,12,16,20,24 --reps 6
    eng shor qpe_4c --cards 4 --circuits qpe --ns 12,16,20,24,28 --reps 6 ;;
  haar)      # E7: Haar random initial states
    eng haar haar_4c --cards 4 --init haar --circuits qft,rand10,partition_heavy,ghz --ns 8,12,16,20,24,28 --reps 3 ;;
  host)      # E11: host dependence, engine and baseline with the host process pinned to fewer cores
    for nc in 4 8 16 64 256; do
      PIN="taskset -c 0-$((nc-1))"
      mkdir -p $R/host
      $PIN $PY_FPGA -u bench/run_engine.py --xclbin $X --engines $NE --swaps 4 --cool-c ${COOL:-84} --cards 4 \
          --circuits qft,rand10 --ns 20,24 --reps 6 --out $R/host/engine_cores${nc}.json >> $L/campaign_host.log 2>&1
      log "host engine cores $nc exit $?"
      $PIN $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --circuits qft --ns 16,20 --reps 4 \
          --out $R/host/baseline_cores${nc}.json >> $L/campaign_host.log 2>&1
      log "host baseline cores $nc exit $?"
    done ;;
  energy)    # E13: loops of at least 30 s with board power sampling, 1, 2, 4 cards
    for c in 1 2 4; do eng energy loop_${c}c --cards $c --power --circuits qft,rand10 --ns 26,28 --reps 12; done ;;
  micro)     # E12
    mkdir -p $R/micro
    $PY_FPGA -u bench/micro_engine.py --xclbin $X --cards 4 --engines $NE --swaps 4 --out $R/micro/engine_4c.json >> $L/campaign_micro.log 2>&1
    log "micro engine exit $?"
    $PY_FPGA -u baseline/micro_baseline.py $V06 4 24 $R/micro/baseline_v06_4c.json >> $L/campaign_micro.log 2>&1
    log "micro baseline exit $?" ;;
  baseline)  # submitted design on the v06 kernel: batched and per gate dispatch, zero and Haar inputs
    mkdir -p $R/baseline
    for mode in "" "--per-gate"; do
      tag=$([ -z "$mode" ] && echo batched || echo pergate)
      $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --circuits qft,ghz,bell,qft_iqft,rand10,partition_heavy \
          --ns 4,8,12,14,16,18,20,22 --reps 6 $mode --out $R/baseline/v06_${tag}.json >> $L/campaign_baseline.log 2>&1
      log "baseline $tag exit $?"
    done
    $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --circuits grover --ns 4,6,8,10,12 --reps 3 \
        --out $R/baseline/v06_grover.json >> $L/campaign_baseline.log 2>&1; log "baseline grover exit $?"
    $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --init haar --circuits qft,rand10,partition_heavy \
        --ns 8,12,16,20 --reps 3 --out $R/baseline/v06_haar.json >> $L/campaign_baseline.log 2>&1; log "baseline haar exit $?" ;;
  cpu)       # E8: Qiskit on the host CPU, same circuits
    mkdir -p $R/cpu
    $PY_FPGA -u bench/run_qiskit_cpu.py --circuits qft,ghz,rand10,qft_iqft --ns 12,16,20,22,24,26,28,30 --reps 6 \
        --out $R/cpu/qiskit_cpu.json >> $L/campaign_cpu.log 2>&1; log "cpu exit $?"
    $PY_FPGA -u bench/run_qiskit_cpu.py --circuits grover --ns 4,6,8,10,12,14,16 --reps 6 \
        --out $R/cpu/qiskit_cpu_grover.json >> $L/campaign_cpu.log 2>&1; log "cpu grover exit $?" ;;
  esac
  log "stage $s end"
done
log "CAMPAIGN_DONE"
