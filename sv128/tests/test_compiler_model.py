"""Compiler plus golden model against Qiskit Statevector (complex128), for every slice path flag combination.

Pass criterion: max |amplitude error| < 1e-12 and 1 minus F < 1e-12 with a Haar random or basis initial state.
"""
import itertools, os, sys
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.quantum_info import Statevector, random_statevector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host"))
from compiler import compile_circuit  # noqa: E402
from model import run_program  # noqa: E402


def ghz(n):
    qc = QuantumCircuit(n); qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return qc


def grover_like(n, it=2):
    qc = QuantumCircuit(n); qc.h(range(n))
    for _ in range(it):
        qc.h(n - 1); qc.mcx(list(range(n - 1)), n - 1); qc.h(n - 1)
        qc.h(range(n)); qc.x(range(n)); qc.h(n - 1); qc.mcx(list(range(n - 1)), n - 1); qc.h(n - 1)
        qc.x(range(n)); qc.h(range(n))
    return qc


def random_circ(n, depth, seed):
    r = np.random.default_rng(seed)
    qc = QuantumCircuit(n)
    for _ in range(depth):
        for q in range(n):
            qc.u(*r.uniform(0, 2 * np.pi, 3), q)
        for _ in range(n // 2):
            a, b = r.choice(n, 2, replace=False)
            g = r.integers(6)
            [lambda: qc.cx(a, b), lambda: qc.cz(a, b), lambda: qc.cp(r.uniform(0, 6), a, b),
             lambda: qc.rzz(r.uniform(0, 6), a, b), lambda: qc.swap(a, b), lambda: qc.rxx(r.uniform(0, 6), a, b)][g]()
        a, b, c = r.choice(n, 3, replace=False)
        qc.ccx(a, b, c)
    return qc


def partition_heavy(n, layers=3):
    """Worst case for the slice paths: non diagonal gates on the top qubits, plus X and CX among them."""
    qc = QuantumCircuit(n)
    for _ in range(layers):
        qc.h(n - 1); qc.rx(0.3, n - 2); qc.x(n - 1); qc.cx(n - 1, n - 2); qc.cx(n - 2, 0)
        qc.rz(0.7, n - 1); qc.cp(0.4, n - 1, n - 2); qc.cp(1.1, 1, n - 1); qc.t(n - 2)
    return qc


def check(qc, L, k, init, flags):
    n = qc.num_qubits
    prog, fmap, st = compile_circuit(qc, L, k, f1=flags[0], f2=flags[1], f3=flags[2], f4=flags[3])
    out = run_program(prog, n, L, fmap, state=init.data.copy())
    ref = init.evolve(qc).data
    err = np.max(np.abs(out - ref))
    inf = 1 - abs(np.vdot(ref, out)) ** 2
    return err, inf, st


def main():
    n = 9
    cases = [("qft", QFT(n, do_swaps=True).decompose()), ("ghz", ghz(n)), ("grover", grover_like(n)),
             ("random", random_circ(n, 4, 7)), ("partition_heavy", partition_heavy(n))]
    worst = 0.0
    fails = 0
    for (name, qc), L, flags in itertools.product(cases, (5, 6, 7), itertools.product((True, False), repeat=4)):
        for init_kind in ("basis", "haar"):
            init = Statevector.from_int(0, 2 ** n) if init_kind == "basis" else random_statevector(2 ** n, seed=11)
            err, inf, st = check(qc, L, L, init, flags)
            worst = max(worst, err)
            ok = err < 1e-12 and inf < 1e-12
            fails += not ok
            if not ok or (init_kind == "haar" and flags == (True, True, True, True) and L == 6):
                print(f"{name:16s} L={L} f={''.join('1' if f else '0' for f in flags)} {init_kind:5s} "
                      f"err={err:.2e} 1-F={inf:.2e} route={st.route} remaps={st.n_remaps} "
                      f"slice_remaps={st.n_remaps_slice} relabels={st.n_relabels} {'OK' if ok else 'FAIL'}")
    print(f"worst max abs error {worst:.2e}; failures {fails}")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
