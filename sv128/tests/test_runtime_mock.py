"""Distributed runtime on the mock pyxrt (1, 2 and 4 cards; device and host exchanges; slice path flags)
against Qiskit Statevector, plus a sampling check."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "host")]
import mock_pyxrt; mock_pyxrt.install()  # noqa: E402
import numpy as np  # noqa: E402
from qiskit.circuit.library import QFT  # noqa: E402
from qiskit.quantum_info import Statevector  # noqa: E402
from runtime import DistSVRuntime  # noqa: E402
from test_compiler_model import ghz, grover_like, random_circ, partition_heavy  # noqa: E402

BDF = ["0000:01:00.1", "0000:21:00.1", "0000:41:00.1", "0000:a1:00.1"]
fails = cases = 0
for C in (1, 2, 4):
    for ne, ns in ((4, 2), (4, 0)):
        rt = DistSVRuntime(BDF[:C], "none", ne, ns)
        for n in (5, 13, 14):
            circs = [("qft", QFT(n).decompose()), ("ghz", ghz(n)), ("grover", grover_like(n, 1)),
                     ("random", random_circ(n, 3, n)), ("partition_heavy", partition_heavy(n, 2))]
            for name, qc in circs:
                for flags in ((True, True, True), (False, False, False)):
                    r = rt.run(qc, shots=8, f1=flags[0], f2=flags[1], f3=flags[2])
                    ref = Statevector(qc).data
                    err = float(np.max(np.abs(r["state"] - ref)))
                    cases += 1
                    ok = err < 1e-12
                    fails += not ok
                    if not ok or (n == 14 and flags[0] and ns):
                        T = r["timing"]
                        print(f"C={C} ne={ne} ns={ns} n={n} P={r['P']} L={r['L']} {name:16s} f={int(flags[0])} err={err:.1e} "
                              f"route={r['stats']['route']} exch_dev={T['n_exch_dev']} exch_host={T['n_exch_host']} "
                              f"cross={T['n_exch_cross_card']} relabel={r['stats']['n_relabels']} {'OK' if ok else 'FAIL'}")
rt = DistSVRuntime(BDF, "none", 4, 2)
qc = random_circ(10, 4, 3)
r = rt.run(qc, shots=20000, seed=3)
p = np.abs(Statevector(qc).data) ** 2
emp = np.zeros_like(p)
for i, c in r["counts"].items():
    emp[i] = c / 20000
tvd = 0.5 * np.abs(emp - p).sum()
ref_tvd = np.mean([0.5 * np.abs(np.random.default_rng(i).multinomial(20000, p / p.sum()) / 20000 - p).sum() for i in range(20)])
print(f"sampling TVD (20000 shots, 10 qubits) = {tvd:.4f}; exact multinomial sampler mean TVD = {ref_tvd:.4f}")
fails += tvd > 1.3 * ref_tvd
print(f"cases={cases} fails={fails}")
sys.exit(1 if fails else 0)
