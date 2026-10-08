# Raw measurements

One JSON file per driver invocation, as written by `bench/run_engine.py`, `baseline/run_baseline.py`,
`bench/run_qiskit_cpu.py` and the microbenchmarks; `*.power.csv` holds every distinct board power and temperature
reading of the cards during that invocation, `*.abort` the reading that crossed a thermal limit.

| Folder | Content |
|---|---|
| `validation_e8w/` | first width validation of the main bitstream on one, two and four cards, Haar random inputs |
| `main/` | main circuit set on four cards (small, Grover, large widths, maximum widths) |
| `scaling/` | strong and weak scaling over one, two and four cards |
| `ablation/` | slice paths F1 to F4 switched off one at a time and together; GHZ variants |
| `part/` | partition on the top qubits (default) against the lowest qubits |
| `shor/` | order finding (N = 15, a = 7) and phase estimation |
| `haar/` | Haar random input states |
| `energy/` | board power sampled during repeated runs |
| `micro/` | microbenchmarks of the engine and of the submitted design |
| `host/` | runs with the host process restricted to 4 to 256 hardware threads |
| `baseline/` | the submitted design (batched and per gate, Haar inputs, large widths, diagonal path ablation) |
| `cpu/` | Qiskit Statevector and Aer on the host CPU, same circuits |
| `_aborted/` | runs stopped by the thermal guard or by a change of the campaign, kept for completeness and not used by the analysis |

Every record of a timed repetition carries the phase times (`timing`), the compiler counters (`stats`) and, for the last
repetition, the comparison with the reference (`metrics`: fidelity, `1 - F` without cancellation, maximum amplitude
error, l2 error, global phase). The first repetition of each configuration is a warm up (`warmup: true`).
