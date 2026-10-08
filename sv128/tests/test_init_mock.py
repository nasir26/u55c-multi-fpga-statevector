"""Arbitrary initial state on the mocked runtime (1, 2, 4 cards) against Qiskit."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "host"), os.path.join(HERE, "..", "..", "bench")]
import mock_pyxrt; mock_pyxrt.install()  # noqa: E402
import numpy as np  # noqa: E402
from qiskit.quantum_info import Statevector  # noqa: E402
from runtime import DistSVRuntime  # noqa: E402
from metrics import compare  # noqa: E402
import circuits as C  # noqa: E402
worst = 0.0
for nc in (1, 2, 4):
    rt = DistSVRuntime(["a", "b", "c", "d"][:nc], "none", 4, 2)
    for n in (6, 13):
        init = C.haar_state(n)
        for qc in (C.qft(n), C.random_circuit(n, 3), C.partition_heavy(n, 3), C.ghz_chain(n)):
            r = rt.run(qc, shots=4, init_state=init)
            m = compare(r["state"], Statevector(init).evolve(qc).data)
            worst = max(worst, m["max_abs_err"]) if np.isfinite(m["max_abs_err"]) else float("inf")
print(f"worst phase aligned max abs error {worst:.2e}")
sys.exit(0 if worst < 1e-12 else 1)
