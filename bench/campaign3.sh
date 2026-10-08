#!/bin/bash
# Follow up stages after campaign2.sh (submitted design on four cards, small v06 bitstream).
#   diagabl : QFT with and without the partition diagonal path (R1.D, R1.Q.4): execution, host compute, barrier time, PCIe bytes
# Author: Nasir Ali, C-DAC Noida.
# usage: campaign3.sh <v06 xclbin> [stage...]
set -u
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/env.sh"
V06=$(readlink -f $1); shift
cd $MW
R=$MW/results/raw; L=$MW/logs
log() { echo "[$(date -Is)] $*" | tee -a $L/campaign.log; }
bl() { local out=$1; shift; mkdir -p $R/baseline
  $PY_FPGA -u baseline/run_baseline.py --xclbin $V06 --cards 4 --out $R/baseline/$out.json "$@" >> $L/campaign_baseline.log 2>&1
  log "baseline/$out exit $?"; }
busy=$(pgrep -fc 'vivado|v\+\+|vitis_hls' || true); [ "$busy" != "0" ] && { log "host not idle"; exit 2; }
STAGES=${@:-diagabl}
for s in $STAGES; do log "followup stage $s start"
  case $s in
  diagabl) bl v06_diag_on  --circuits qft --ns 8,12,16,18,20 --reps 4
           bl v06_diag_off --circuits qft --ns 8,12,16,18,20 --reps 4 --no-diag ;;
  esac
  log "followup stage $s end"
done
log "FOLLOWUP_DONE"
