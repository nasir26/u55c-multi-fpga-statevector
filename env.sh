# Source in every shell from this directory: source env.sh
# Package version: Python environments, TeX Live, caches and temporary files all live inside this directory.
export MW="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WS="$MW"
export TMPDIR=$MW/tmp; mkdir -p $TMPDIR
export XDG_CACHE_HOME=$MW/cache
export PIP_CACHE_DIR=$MW/cache/pip
export MPLCONFIGDIR=$MW/cache/matplotlib
export MAMBA_ROOT_PREFIX=$MW/envs/.mamba
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export XILINX_LOCAL_USER_DATA=no
if [ -f /opt/xilinx/xrt/setup.sh ]; then source /opt/xilinx/xrt/setup.sh >/dev/null 2>&1; fi
export PYTHONPATH=/opt/xilinx/xrt/python${PYTHONPATH:+:$PYTHONPATH}
vitis_env() { source ${VITIS_SETTINGS:-/tools/Xilinx/Vitis/2023.2/settings64.sh}; }
export PLATFORM=${PLATFORM:-xilinx_u55c_gen3x16_xdma_3_202210_1}
export PY_FPGA=$MW/envs/fpga/bin/python
export PY_CPU=$MW/envs/cpu/bin/python
if [ -d $MW/envs/texlive/bin/x86_64-linux ]; then export PATH=$MW/envs/texlive/bin/x86_64-linux:$PATH; fi
# card addresses of this host (user function .1 of each card); see README step 2
if [ -f $MW/cards.env ]; then source $MW/cards.env; fi
true
