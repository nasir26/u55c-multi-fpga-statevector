#!/bin/bash
# Measurement campaign in two phases (card 21 cannot hold the engine bitstream safely at daytime ambient):
#   day   : engine on 1 and 2 cards (cards 41, a1), baseline on 4 cards (small v06 bitstream), baseline microbenchmarks
#   night : engine on 4 cards; starts when every parked card is below 78 C
# Every engine configuration parks the cards on the v06 bitstream, waits below ${COOL:-84} C, loads the engine, runs,
# parks again; any card at 90 C (FPGA) or 85 C (HBM) stops the configuration.
# Author: Nasir Ali, C-DAC Noida.
# usage: campaign2.sh <engine xclbin> <engines per card> <v06 xclbin> day|night [stage...]
set -u
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/env.sh"
X=$(readlink -f $1); NE=$2; V06=$(readlink -f $3); PHASE=$4; shift 4
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
temps_ok() { for b in 0000:01:00.1 0000:21:00.1 0000:41:00.1 0000:a1:00.1; do
  t=$(cat /sys/bus/pci/devices/$b/xmc.u.*/xmc_fpga_temp); [ $t -ge ${1:-78} ] && return 1; done; return 0; }
busy=$(pgrep -fc 'vivado|v\+\+|vitis_hls' || true); [ "$busy" != "0" ] && { log "host not idle"; exit 2; }

if [ $PHASE = day ]; then
  STAGES=${@:-scaling12 ablation2 part2 shor2 host2 energy12 baseline microbl}
  for s in $STAGES; do log "day stage $s start"
    case $s in
    scaling12) for c in 1 2; do eng scaling strong_${c}c --cards $c --circuits qft,ghz,rand10 --ns 20,22,24,26,28 --reps 6; done
               eng scaling weak_1c --cards 1 --circuits qft,rand10 --ns 26,27 --reps 4
               eng scaling weak_2c --cards 2 --circuits qft,rand10 --ns 27,28 --reps 4 ;;
    ablation2) eng ablation flags_2c --cards 2 --circuits qft,ghz,rand10,partition_heavy,grover --ns 16,20,24,28 \
                   --flags 111a,011a,101a,110a,1110,0000 --reps 6
               eng ablation ghz_variants_2c --cards 2 --circuits ghz,ghz_top,ghz_log --ns 16,20,24,28 --flags 1110,1111 --reps 6 ;;
    part2)     eng part default_2c --cards 2 --circuits qft,ghz,grover --ns 16,20,24 --reps 6
               eng part low01_2c --cards 2 --circuits qft,ghz,grover --ns 16,20,24 --reps 6 --part 0,1 ;;
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
    esac
    log "day stage $s end"
  done
  log "DAY_DONE"
else
  if [ "${NIGHT_GATE:-1}" = 1 ]; then
    log "night phase: waiting until every parked card is below 78 C"
    until temps_ok 78; do sleep 60; done
  else
    log "four card phase started without the ambient gate (author decision); per configuration cooling and abort limits apply"
  fi
  STAGES=${@:-main4 scaling4 ablation4 part4 energy4 micro4 host4}
  for s in $STAGES; do log "night stage $s start"
    case $s in
    main4)     eng main small_4c --cards 4 --circuits qft,ghz,bell,qft_iqft,rand10,partition_heavy --ns 4,6,8,10,12,14,16,18,20,22 --reps 11
               eng main grover_4c --cards 4 --circuits grover --ns 4,6,8,10,12,14,16 --reps 6
               eng main large_4c --cards 4 --circuits qft,ghz,rand10,qft_iqft --ns 24,26,28 --reps 6
               eng main max_4c --cards 4 --circuits ghz,qft,rand10 --ns 29,30,31 --reps 4 ;;
    scaling4)  eng scaling strong_4c --cards 4 --circuits qft,ghz,rand10 --ns 20,22,24,26,28 --reps 6
               eng scaling weak_4c --cards 4 --circuits qft,rand10 --ns 28,29 --reps 4 ;;
    ablation4) eng ablation flags_4c --cards 4 --circuits qft,ghz,rand10,partition_heavy,grover --ns 16,20,24,28 \
                   --flags 111a,011a,101a,110a,1110,0000 --reps 6
               eng ablation ghz_variants_4c --cards 4 --circuits ghz,ghz_top,ghz_log --ns 16,20,24,28 --flags 1110,1111 --reps 6 ;;
    part4)     eng part default_4c --cards 4 --circuits qft,ghz,grover --ns 16,20,24 --reps 6
               eng part low01_4c --cards 4 --circuits qft,ghz,grover --ns 16,20,24 --reps 6 --part 0,1 ;;
    energy4)   eng energy loop_4c --cards 4 --power --circuits qft,rand10 --ns 26,28 --reps 12 ;;
    micro4)    mkdir -p $R/micro
               $PY_FPGA -u bench/micro_engine.py --xclbin $X --cards 4 --engines $NE --swaps 4 --out $R/micro/engine_4c.json >> $L/campaign_micro.log 2>&1
               log "micro engine exit $?"
               $PY_FPGA -c "import uuid, pyxrt; [pyxrt.device(b).load_xclbin('$V06') for b in ['0000:01:00.1','0000:21:00.1','0000:41:00.1','0000:a1:00.1']]" ;;
    host4)     mkdir -p $R/host
               for nc in 4 8 16 64 256; do
                 $PY_FPGA -u bench/run_engine.py --xclbin $X --engines $NE --swaps 4 --cool-c ${COOL:-84} --park-xclbin $V06 --cards 4 \
                    --circuits qft,rand10 --ns 20,24 --reps 6 --out $R/host/engine4c_cores${nc}.json --pin-cores $nc >> $L/campaign_host.log 2>&1
                 log "host engine4c cores $nc exit $?"
               done ;;
    esac
    log "night stage $s end"
  done
  log "NIGHT_DONE"
fi
