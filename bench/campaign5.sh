#!/bin/bash
# Follow up of campaign4.sh: instances lost to thermal stops of earlier stages (2026-10-08).
# Replaces the unfinished part of campaign2.sh (night and day) and campaign3.sh. Grover runs only at widths where its
# oracle is native on the engine (n <= 14 on one and two cards, n <= 16 on four cards); wider Grover instances would be
# decomposed into thousands of gates per iteration for hundreds of iterations.
# Author: Nasir Ali, C-DAC Noida.
# usage: campaign4.sh <engine xclbin> <engines per card> <v06 xclbin> [stage...]
set -u
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/env.sh"
X=$(readlink -f $1); NE=$2; V06=$(readlink -f $3); shift 3
cd $MW
R=$MW/results/raw; L=$MW/logs
log() { echo "[$(date -Is)] $*" | tee -a $L/campaign.log; }
eng() { local st=$1 out=$2; shift 2; mkdir -p $R/$st
  $PY_FPGA -u bench/run_engine.py --xclbin $X --engines $NE --swaps 4 --cool-c ${COOL:-84} --park-xclbin $V06 \
      --out $R/$st/$out.json "$@" >> $L/campaign_$st.log 2>&1
  log "$st/$out exit $?"; }
bl() { local out=$1; shift; mkdir -p $R/baseline
  $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --out $R/baseline/$out.json "$@" >> $L/campaign_baseline.log 2>&1
  log "baseline/$out exit $?"; }
busy=$(pgrep -fc 'vivado|v\+\+|vitis_hls' || true); [ "$busy" != "0" ] && { log "host not idle"; exit 2; }
log "campaign5 (follow up, commit $(git rev-parse --short HEAD)) started"
STAGES=${@:-iqft4}
for s in $STAGES; do log "stage $s start"
  case $s in
  abl4fix)   eng ablation flags_4c --cards 4 --circuits qft,ghz,rand10,partition_heavy --ns 16,20,24,28 \
                 --flags 111a,011a,101a,110a,1110,0000 --reps 6
             eng ablation flags_grover_4c --cards 4 --circuits grover --ns 8,12,14 --flags 111a,011a,101a,110a,1110,0000 --reps 6
             eng part low01_grover_4c --cards 4 --circuits grover --ns 8,12,14 --reps 6 --part 0,1 ;;
  iqft4)     eng main large_iqft_4c --cards 4 --circuits qft_iqft --ns 24,26,28 --reps 6
             eng main grover16_4c --cards 4 --circuits grover --ns 16 --reps 3
             eng haar haar_4c_part2 --cards 4 --init haar --circuits partition_heavy,ghz --ns 8,12,16,20,24,28 --reps 3 ;;
  main4rest) eng main grover_4c --cards 4 --circuits grover --ns 4,6,8,10,12,14,16 --reps 6 ;;
  max31)     eng main max31_4c --cards 4 --circuits ghz,qft --ns 31 --reps 2 ;;
  scaling4)  eng scaling strong_4c --cards 4 --circuits qft,ghz,rand10 --ns 20,22,24,26,28 --reps 6
             eng scaling weak_4c --cards 4 --circuits qft,rand10 --ns 28,29 --reps 4 ;;
  ablation4) eng ablation flags_4c --cards 4 --circuits qft,ghz,rand10,partition_heavy --ns 16,20,24,28 \
                 --flags 111a,011a,101a,110a,1110,0000 --reps 6 ;&
  ablation4rest)
             eng ablation flags_grover_4c --cards 4 --circuits grover --ns 8,12,14 --flags 111a,011a,101a,110a,1110,0000 --reps 6
             eng ablation ghz_variants_4c --cards 4 --circuits ghz,ghz_top,ghz_log --ns 16,20,24,28 --flags 1110,1111 --reps 6 ;;
  part4)     eng part default_4c --cards 4 --circuits qft,ghz --ns 16,20,24 --reps 6
             eng part low01_4c --cards 4 --circuits qft,ghz --ns 16,20,24 --reps 6 --part 0,1
             eng part default_grover_4c --cards 4 --circuits grover --ns 8,12,14 --reps 6
             eng part low01_grover_4c --cards 4 --circuits grover --ns 8,12,14 --reps 6 --part 0,1 ;;
  shor4)     eng shor shor15_4c --cards 4 --circuits shor15 --ns 12,16,20,24 --reps 6
             eng shor qpe_4c --cards 4 --circuits qpe --ns 12,16,20,24,28 --reps 6 ;;
  haar4)     eng haar haar_4c --cards 4 --init haar --circuits qft,rand10,partition_heavy,ghz --ns 8,12,16,20,24,28 --reps 3 ;;
  energy4)   eng energy loop_4c --cards 4 --power --circuits qft,rand10 --ns 26,28 --reps 12 ;;
  micro4)    mkdir -p $R/micro
             $PY_FPGA -u bench/micro_engine.py --xclbin $X --cards 4 --engines $NE --swaps 4 --out $R/micro/engine_4c.json >> $L/campaign_micro.log 2>&1
             log "micro engine exit $?"
             $PY_FPGA -c "import uuid, os, pyxrt; [pyxrt.device(b).load_xclbin('$V06') for b in os.environ.get('QSIM_BDFS', '0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1').split(',')]" ;;
  host4)     mkdir -p $R/host
             for nc in 4 8 16 64 256; do
               $PY_FPGA -u bench/run_engine.py --xclbin $X --engines $NE --swaps 4 --cool-c ${COOL:-84} --park-xclbin $V06 --cards 4 \
                  --circuits qft,rand10 --ns 20,24 --reps 6 --out $R/host/engine4c_cores${nc}.json --pin-cores $nc >> $L/campaign_host.log 2>&1
               log "host engine4c cores $nc exit $?"
             done ;;
  scaling12) for c in 1 2; do eng scaling strong_${c}c --cards $c --circuits qft,ghz,rand10 --ns 20,22,24,26,28 --reps 6; done
             eng scaling weak_1c --cards 1 --circuits qft,rand10 --ns 26,27 --reps 4
             eng scaling weak_2c --cards 2 --circuits qft,rand10 --ns 27,28 --reps 4 ;;
  ablation2) eng ablation flags_2c --cards 2 --circuits qft,ghz,rand10,partition_heavy --ns 16,20,24,28 \
                 --flags 111a,011a,101a,110a,1110,0000 --reps 6
             eng ablation flags_grover_2c --cards 2 --circuits grover --ns 8,12,14 --flags 111a,011a,101a,110a,1110,0000 --reps 6
             eng ablation ghz_variants_2c --cards 2 --circuits ghz,ghz_top,ghz_log --ns 16,20,24,28 --flags 1110,1111 --reps 6 ;;
  part2)     eng part default_2c --cards 2 --circuits qft,ghz --ns 16,20,24 --reps 6
             eng part low01_2c --cards 2 --circuits qft,ghz --ns 16,20,24 --reps 6 --part 0,1
             eng part default_grover_2c --cards 2 --circuits grover --ns 8,12,14 --reps 6
             eng part low01_grover_2c --cards 2 --circuits grover --ns 8,12,14 --reps 6 --part 0,1 ;;
  shor2)     eng shor shor15_2c --cards 2 --circuits shor15 --ns 12,16,20,24 --reps 6
             eng shor qpe_2c --cards 2 --circuits qpe --ns 12,16,20,24,28 --reps 6 ;;
  host2)     mkdir -p $R/host
             for nc in 4 8 16 64 256; do
               $PY_FPGA -u bench/run_engine.py --xclbin $X --engines $NE --swaps 4 --cool-c ${COOL:-84} --park-xclbin $V06 --cards 2 \
                  --circuits qft,rand10 --ns 20,24 --reps 6 --out $R/host/engine2c_cores${nc}.json --pin-cores $nc >> $L/campaign_host.log 2>&1
               log "host engine2c cores $nc exit $?"
               $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --circuits qft --ns 16,20 --reps 4 --pin-cores $nc \
                  --out $R/host/baseline4c_cores${nc}.json >> $L/campaign_host.log 2>&1
               log "host baseline4c cores $nc exit $?"
             done ;;
  energy12)  for c in 1 2; do eng energy loop_${c}c --cards $c --power --circuits qft,rand10 --ns 26,28 --reps 12; done ;;
  baseline)  bl v06_batched --circuits qft,ghz,bell,qft_iqft,rand10,partition_heavy --ns 4,8,12,14,16,18,20,22 --reps 6
             bl v06_pergate --per-gate --circuits qft,ghz,bell,qft_iqft,rand10,partition_heavy --ns 4,8,12,14,16,18,20 --reps 6
             bl v06_grover --circuits grover --ns 4,6,8,10,12 --reps 3
             bl v06_haar --init haar --circuits qft,rand10,partition_heavy --ns 8,12,16,20 --reps 3
             bl v06_large --circuits qft,ghz --ns 24,26,28 --reps 3 ;;
  microbl)   mkdir -p $R/micro
             $PY_FPGA -u baseline/micro_baseline.py $V06 4 26 $R/micro/baseline_v06_4c.json >> $L/campaign_micro.log 2>&1
             log "micro baseline exit $?" ;;
  diagabl)   bl v06_diag_on  --circuits qft --ns 8,12,16,18,20 --reps 4
             bl v06_diag_off --circuits qft --ns 8,12,16,18,20 --reps 4 --no-diag ;;
  *)         log "unknown stage $s" ;;
  esac
  log "stage $s end"
done
log "CAMPAIGN5_DONE"
