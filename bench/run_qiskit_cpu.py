#!/usr/bin/env python3
"""E8: Qiskit statevector wall clock on the host CPU for exactly the FPGA circuits (complex128).

Author: Nasir Ali, C-DAC Noida.

Backends (simulation time only; circuit construction and transpilation are outside the timed region and identical
to the FPGA runs, which receive the same circuit objects from bench/circuits.py):
  sv     : qiskit.quantum_info.Statevector(init).evolve(qc)            (NumPy, complex128)
  aer    : AerSimulator(method="statevector", precision="double"), default threads, default fusion
  aer1   : the same with max_parallel_threads = 1
Records the wall clock of the simulate call and Aer's own time_taken; repetition 0 is a warm up.
usage: run_qiskit_cpu.py --circuits qft,ghz --ns 12,16,20 --backends sv,aer,aer1 --reps 6 --out R.json
"""
import argparse, json, os, platform, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--circuits", required=True)
    ap.add_argument("--ns", required=True)
    ap.add_argument("--backends", default="sv,aer,aer1")
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--sv-max", type=int, default=24, help="largest n for the single threaded NumPy Statevector")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import qiskit, qiskit_aer
    from qiskit import transpile
    from qiskit.quantum_info import Statevector
    from qiskit_aer import AerSimulator
    from run_engine import build
    cpu = [l for l in open("/proc/cpuinfo") if l.startswith("model name")]
    meta = dict(cmd=" ".join(sys.argv), start=time.strftime("%Y-%m-%dT%H:%M:%S%z"), qiskit=qiskit.__version__,
                qiskit_aer=qiskit_aer.__version__, numpy=np.__version__, python=platform.python_version(),
                cpu_model=cpu[0].split(":", 1)[1].strip() if cpu else None, n_logical_cpus=os.cpu_count(),
                governor=open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read().strip()
                if os.path.exists("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") else None)
    recs = []
    for name in a.circuits.split(","):
        for n in [int(x) for x in a.ns.split(",")]:
            qc = build(name, n)
            for be in a.backends.split(","):
                if be == "sv" and n > a.sv_max:
                    continue
                if be.startswith("aer"):
                    sim = AerSimulator(method="statevector", precision="double",
                                       **({"max_parallel_threads": 1} if be == "aer1" else {}))
                    q2 = qc.copy(); q2.save_statevector()
                    t = transpile(q2, sim, optimization_level=0)
                for rep in range(a.reps):
                    t0 = time.perf_counter()
                    if be == "sv":
                        Statevector.from_int(0, 2 ** n).evolve(qc)
                        inner = None
                    else:
                        res = sim.run(t).result()
                        inner = res.time_taken
                    wall = time.perf_counter() - t0
                    recs.append(dict(circuit=name, n=n, backend=be, rep=rep, warmup=rep == 0, wall_s=wall,
                                     aer_time_taken_s=inner, threads=(1 if be in ("sv", "aer1") else "default")))
                    print(f"{name:14s} n={n:2d} {be:5s} rep={rep} wall={wall:.4f}s", flush=True)
                    json.dump(dict(meta=meta, records=recs), open(a.out, "w"))
    meta["end"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    json.dump(dict(meta=meta, records=recs), open(a.out, "w"))


if __name__ == "__main__":
    main()
