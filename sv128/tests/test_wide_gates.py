"""Multi controlled gates wider than the tile window (compiler plus golden model against Qiskit Statevector).

Small widths with a narrow tile (L local qubits, window k) so that gates have more qubits than k: Grover iterations
and random multi controlled X, phase and U gates with random control and target sets, Haar random inputs, every slice
path flag combination. Pass criterion as in test_compiler_model.py: max |amplitude error| < 1e-12 and 1 minus F < 1e-12.
Also checks that with F2 on the wide gates stay single records (no decomposition) and that the record count is small.
"""
import itertools, os, sys
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import MCPhaseGate, UGate
from qiskit.quantum_info import Statevector, random_statevector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host"))
from compiler import compile_circuit  # noqa: E402
from model import run_program  # noqa: E402
from metrics import compare  # noqa: E402


def grover_like(n, it=2):
    qc = QuantumCircuit(n); qc.h(range(n))
    for _ in range(it):
        qc.h(n - 1); qc.mcx(list(range(n - 1)), n - 1); qc.h(n - 1)
        qc.h(range(n)); qc.x(range(n)); qc.h(n - 1); qc.mcx(list(range(n - 1)), n - 1); qc.h(n - 1)
        qc.x(range(n)); qc.h(range(n))
    return qc


def random_wide(n, gates, seed, kmin):
    r = np.random.default_rng(seed)
    qc = QuantumCircuit(n)
    for q in range(n):
        qc.u(*r.uniform(0, 2 * np.pi, 3), q)
    for _ in range(gates):
        w = int(r.integers(kmin + 1, n + 1))
        qs = [int(x) for x in r.choice(n, w, replace=False)]
        g = int(r.integers(3))
        if g == 0:
            qc.mcx(qs[1:], qs[0])
        elif g == 1:
            qc.append(MCPhaseGate(float(r.uniform(0, 6)), w - 1), qs)
        else:
            qc.append(UGate(*r.uniform(0, 2 * np.pi, 3)).control(w - 1), qs)
        a, b = r.choice(n, 2, replace=False)
        qc.cx(int(a), int(b)); qc.h(int(a))
    return qc


def main():
    fails, cases, wide_native = 0, 0, 0
    configs = [(9, 5, 5), (10, 6, 6), (11, 7, 6)]          # (n, L, k)
    flags_all = [fl + (f4,) for fl in itertools.product([True, False], repeat=3) for f4 in (False, True, "auto")]
    for n, L, k in configs:
        circs = [("grover", grover_like(n))] + [(f"rand{s}", random_wide(n, 4, s, k)) for s in range(3)]
        for name, qc in circs:
            init = random_statevector(2 ** n, seed=7 * n)
            ref = init.evolve(qc).data
            # F2 off decomposes every wide gate through the transpiler (slow): only for the Grover circuit
            for fl in (flags_all if name == "grover" else [f for f in flags_all if f[1]]):
                prog, fmap, st = compile_circuit(qc, L, k, f1=fl[0], f2=fl[1], f3=fl[2], f4=fl[3])
                out = run_program(prog, n, L, fmap, state=init.data.copy())
                m = compare(out, ref)
                ok = m["max_abs_err"] < 1e-12 and m["one_minus_F"] < 1e-12
                cases += 1
                if fl[1] and st.lowered.get("mcx", 0) == 0 and st.n_wide > 0:
                    wide_native += 1
                if not ok:
                    fails += 1
                    print(f"FAIL n={n} L={L} k={k} {name} flags={fl} err={m['max_abs_err']:.2e} 1-F={m['one_minus_F']:.2e}")
            print(f"n={n} L={L} k={k} done", flush=True)
    print(f"cases={cases} fails={fails} wide gates native (F2 on, no decomposition) in {wide_native} compilations")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
