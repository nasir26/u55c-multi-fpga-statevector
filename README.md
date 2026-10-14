# Multi FPGA complex128 statevector simulator on four Alveo U55C

An exact statevector quantum circuit simulator that distributes a complex128 state over the HBM of one, two or four
AMD Alveo U55C cards in one host. Every gate that does not need amplitudes held by another card runs on the FPGAs;
only the remaining gates move data, inside a card by a device copy kernel and across cards through host memory.
The repository holds the HLS kernels, the host compiler and runtime, the submitted design used as baseline, the
experiment drivers, the analysis scripts and every raw measurement of the revision.

## Design in short

- **One primitive.** Every gate is compiled into MUX2 records `(t, c, M0, M1)`: the 2x2 complex128 matrix `M1` is
  applied to the amplitude pairs along qubit `t` whose index has all bits of the control mask `c` set, `M0` to the
  others. Multi controlled gates (Toffoli, the Grover oracle) are one record. Matrices are float64.
- **Slices.** The state is split into `S = C x P` slices of `2^L` amplitudes (`C` cards, `P` engines per card). The
  top `log2 C` qubits select the card. Each record carries a slice enable, so gates on slice qubits run without data
  movement when they are diagonal (F1), slice controlled (F2) or a slice permutation (F3). A compiler rewrite (F4)
  turns X type gates with a slice target into slice permutations. Other gates trigger a remap (global to local swap).
- **Pass engine.** One compute unit per group of HBM pseudo channels streams its slice through on chip tiles of up to
  `2^11` amplitudes, applying every record of a pass in one read and one write of the slice, two amplitude pairs per
  cycle at II = 1, with 512 bit HBM ports.
- **Main bitstream** (`builds/sv128_e8w`): 8 engines per card with 4 pseudo channels each (all 32 channels of the
  card, 16 GiB), 4 exchange units (`sv_swap`) reaching all channels, 300 MHz.

### Why eight engines, and why the submitted kernel used eight banks

The single card design of the 30 qubit work uses sixteen HBM banks in complex64. Widened to complex128, the sixteen
bank kernel failed to route (congestion), so the submitted multi card kernel `v06` uses eight data banks plus one
port for the gate sequence (each bank needs its own AXI port), nine of 32 pseudo channels per card. The revised engine
decouples memory reach from port count: eight engines with four pseudo channels each reach every channel. A build with
sixteen complex128 engines (`builds/sv128_e16w`) placed but failed routing; its reports and link log are kept.

## Layout

| Path | What |
|---|---|
| `sv128/kernels/` | engine kernel `sv128_engine.cpp` (HLS, complex128) and its C test bench |
| `kernels/sv_swap.cpp` | exchange kernel (moves 512 bit words between pseudo channels), shared with the 30 qubit work |
| `sv128/host/` | `isa.py` (record encoding), `compiler.py` (Qiskit circuit to records: fusion, routing F1 to F4, wide gate placement, pass tiling, remap scheduling), `model.py` (NumPy golden model), `runtime.py` (XRT runtime for 1, 2, 4 cards), `metrics.py` |
| `sv128/tests/` | compiler against golden model (480 cases), wide multi controlled gates (180 cases), mocked runtime, C simulation, hardware suite |
| `sv128/build/` | `build_xo.sh` (HLS), `link.sh` (writes the link configuration and links) |
| `baseline/` | the submitted design: original host `fpga_simulator_v06.py`, distributed driver `dist_v06.py` (three barrier exchange through shared host memory), its experiment driver and microbenchmarks |
| `builds/` | per bitstream: link configuration, sha256 and info of the bitstream used for the measurements, Vivado utilisation reports, timing summary extract; `v06/` also holds the kernel source and build script |
| `bench/` | `run_engine.py` (all engine experiments), `circuits.py` (circuit generators, fixed seeds), `run_qiskit_cpu.py` (Qiskit on the host), `micro_engine.py`, `fpga_power.py` (board power and temperature sampler with abort limits), `thermal_soak.py`, campaign scripts |
| `scripts/` | `make_tables.py`, `make_figures.py`, `model_v06.py` (microbenchmark model of the submitted design), `closed_forms.py`, `capture_manifest.py`, `compare_machines.py`, `export_circuits.py` |
| `results/raw/` | every measurement as written by the drivers (JSON records, power and temperature CSV, abort markers) |
| `results/hardware_manifest.json` | cards, shell, XRT, host CPU and memory, bitstream hashes at measurement time |
| `paper/generated/`, `figures/` | tables, macros and figures generated from `results/raw/` |
| `paper/manuscript/` | the manuscript (single LaTeX source, bibliography, figures and the compiled PDF) |
| `logs/` | build and campaign logs |
| `setup/` | Python environment specifications and setup script |

Bitstreams (`*.xclbin`, 47 MB and 66 MB) and kernel objects are not stored in this repository; rebuild them as below and
compare against the stored `sha256` files.

## Requirements

- Alveo U55C cards with shell `xilinx_u55c_gen3x16_xdma_base_3` (platform `xilinx_u55c_gen3x16_xdma_3_202210_1`), XRT 2.16
  with its Python bindings (`/opt/xilinx/xrt/python`, Python 3.8)
- Python environments from `setup/env_fpga.yml` (Python 3.8, Qiskit 1.2.4, Qiskit Aer 0.15.1, NumPy 1.24.4) and
  `setup/env_cpu.yml` (analysis); `bash setup/setup_envs.sh` creates both with micromamba inside the repository
- Vitis 2023.2 only to rebuild bitstreams or run the C simulation

## Quick start

```
bash setup/setup_envs.sh && source env.sh
$PY_FPGA sv128/tests/test_compiler_model.py          # compiler and golden model against Qiskit, no FPGA needed
$PY_FPGA sv128/tests/test_wide_gates.py              # wide multi controlled gates, no FPGA needed
$PY_FPGA sv128/tests/test_runtime_mock.py            # runtime with mocked XRT, no FPGA needed
$PY_FPGA baseline/test_exchange_math.py              # exchange arithmetic of the submitted design
```

Card addresses are taken from `QSIM_BDFS` (four cards), `QSIM_CARDS1` and `QSIM_CARDS2`, for example in `cards.env`,
which `env.sh` reads:

```
export QSIM_BDFS=0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1
export QSIM_CARDS1=0000:41:00.1
export QSIM_CARDS2=0000:41:00.1,0000:a1:00.1
```

Hardware checks:

```
$PY_FPGA sv128/tests/test_hw.py builds/sv128_e8w/sv.xclbin 8 4 12,16,20
$PY_FPGA baseline/check_hw.py builds/v06/quantum_fpga_kernel_complex128_v06.xclbin 4 8,12,16
```

## Rebuilding the bitstreams

```
bash builds/sv_xo/build_swap.sh                       # exchange kernel object
bash sv128/build/build_xo.sh xo_w512 -D SV_WIDE        # engine kernel object, 512 bit ports
bash sv128/build/link.sh sv128_e8w xo_w512 8 4 4       # 8 engines x 4 pseudo channels, 4 exchange units
bash builds/v06/build.sh                               # submitted kernel v06
```

## Measurements

`bench/campaign_full.sh <engine xclbin> 8 <v06 xclbin>` runs every stage on one host: thermal soak, width validation,
the main circuit set on four cards, scaling over one, two and four cards, ablations of F1 to F4, partition choice,
order finding and phase estimation, Haar random inputs, board energy, microbenchmarks, host core sensitivity, the
submitted design (batched and per gate, diagonal path ablation) and Qiskit on the host CPU. Every instance with
`n <= 30` is compared amplitude by amplitude with Qiskit (Statevector up to `n = 20`, Aer in double precision above);
the records carry the fidelity, `1 - F` computed without cancellation, and the maximum amplitude error.

Thermal guard: before each repetition the cards are parked on the small `v06` bitstream and cooled below the campaign's
cooling target (84 C) if a card is at 85 C (FPGA) or 80 C (HBM); a run that crosses 90 C (FPGA) or 85 C (HBM) is kept, flagged and listed under
`thermal_stops`, and the campaign continues with the next instance. On the measurement host one card runs markedly
hotter than the others; runs stopped by the guard are kept in `results/raw/_aborted/` and in the logs.

`scripts/make_tables.py` and `scripts/make_figures.py` regenerate every table and figure from `results/raw/` only.
`scripts/compare_machines.py` compares the measurements of two hosts configuration by configuration.

## Workflow: from a hardware run to the paper

```
sv128/ + baseline/        engine, compiler, runtime and the submitted design, tested without hardware (sv128/tests/)
      |  sv128/build/*.sh, builds/v06/build.sh
      v
builds/<name>/            bitstream hash, metadata, utilisation and timing reports
      |  bench/campaign*.sh on the four cards and on the host CPU
      v
results/raw/              one JSON record per run, with power and temperature logs
      |  scripts/make_tables.py, scripts/make_figures.py
      v
paper/generated/          every table and number of the paper, as LaTeX
      |
      v
paper/manuscript/         manuscript.tex and manuscript.pdf
```

No number in the manuscript is typed by hand: each one is a macro or a table in `paper/generated/`, produced from
`results/raw/`. Runs that were stopped or affected by a driver bug are kept in `results/raw/_aborted/` with the reason
in `results/raw/README.md`, and are not used by the analysis.

## Citation

N. Ali, "Multi FPGA Quantum Circuit Simulation: A Distributed Statevector Architecture on Four Xilinx Alveo U55C
Accelerators", Research Square preprint (2026), doi:10.21203/rs.3.rs-10128153/v1 (under major revision, The Journal of
Supercomputing). The single card design: A. Tiwari, N. Ali et al., "FPGA Based Quantum Circuit Simulator: Processing
30 Qubit Systems", doi:10.21203/rs.3.rs-8581344/v1.

## Author

Nasir Ali, Centre for Development of Advanced Computing (C-DAC), Noida, India.

## License

MIT, see `LICENSE`.
