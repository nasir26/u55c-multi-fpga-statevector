"""Benchmark circuits of the revision (fixed seeds). The same circuit objects are run on the FPGA engine, on the
baseline design and on Qiskit for the CPU timings; QASM copies are written by export_qasm().

Author: Nasir Ali, C-DAC Noida.
"""
import math, os
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT

SEED = 2026


def qft(n, inverse=False):
    qc = QFT(n, do_swaps=True, inverse=inverse).decompose()
    qc.name = "iqft" if inverse else "qft"
    return qc


def qft_basis(n, bits):
    """QFT applied to a computational basis state given as an integer (qubit 0 = least significant bit)."""
    qc = QuantumCircuit(n, name=f"qft_b{bits}")
    for q in range(n):
        if (bits >> q) & 1:
            qc.x(q)
    qc.compose(qft(n), inplace=True)
    return qc


def qft_roundtrip(n, seed=SEED):
    """Random product state, QFT, inverse QFT: output equals the input state."""
    r = np.random.default_rng(seed + n)
    qc = QuantumCircuit(n, name="qft_iqft")
    for q in range(n):
        qc.u(*r.uniform(0, 2 * math.pi, 3), q)
    qc.compose(qft(n), inplace=True)
    qc.compose(qft(n, inverse=True), inplace=True)
    return qc


def ghz_chain(n):
    qc = QuantumCircuit(n, name="ghz")
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return qc


def ghz_rooted_top(n):
    """GHZ with the root on the top qubit and a CX fan out to every other qubit (same state as ghz_chain)."""
    qc = QuantumCircuit(n, name="ghz_top")
    qc.h(n - 1)
    for i in range(n - 2, -1, -1):
        qc.cx(n - 1, i)
    return qc


def ghz_logdepth(n):
    """Logarithmic depth GHZ: CX doubling tree from qubit 0 (Cruz et al. 2019)."""
    qc = QuantumCircuit(n, name="ghz_log")
    qc.h(0)
    have = 1
    while have < n:
        for i in range(min(have, n - have)):
            qc.cx(i, have + i)
        have *= 2
    return qc


def bell(n):
    qc = QuantumCircuit(n, name="bell")
    qc.h(0); qc.cx(0, n - 1)
    return qc


def grover_kopt(n, marked=None):
    """Grover search for one marked state (default all ones) with k_opt = floor(pi / (4 theta)) iterations,
    theta = asin(2^(-n/2)) (Boyer et al.)."""
    marked = (1 << n) - 1 if marked is None else marked
    th = math.asin(2 ** (-n / 2))
    k = math.floor(math.pi / (4 * th))
    qc = QuantumCircuit(n, name="grover")
    qc.h(range(n))
    zeros = [q for q in range(n) if not (marked >> q) & 1]

    def mcz():
        qc.h(n - 1); qc.mcx(list(range(n - 1)), n - 1); qc.h(n - 1)
    for _ in range(k):
        if zeros:
            qc.x(zeros)
        mcz()
        if zeros:
            qc.x(zeros)
        qc.h(range(n)); qc.x(range(n)); mcz(); qc.x(range(n)); qc.h(range(n))
    qc.metadata = dict(k=k, theta=th, P_analytic=math.sin((2 * k + 1) * th) ** 2, marked=marked)
    return qc


def shor_qpe_7_mod_15(t=5):
    """Quantum phase estimation of a = 7 mod 15 (period 4) with a t qubit counting register and 4 work qubits;
    controlled powers of the modular multiplier built from the textbook permutation circuits."""
    qc = QuantumCircuit(t + 4, name=f"shor15_t{t}")
    qc.h(range(t))
    qc.x(t)    # work register = |1>

    def c_amod15(power):
        U = QuantumCircuit(4)
        for _ in range(power % 4):
            U.swap(2, 3); U.swap(1, 2); U.swap(0, 1)
            for q in range(4):
                U.x(q)
        return U.to_gate().control(1)
    for j in range(t):
        qc.append(c_amod15(2 ** j), [j] + [t + i for i in range(4)])
    qc.compose(QFT(t, inverse=True, do_swaps=True).decompose(), range(t), inplace=True)
    qc.metadata = dict(a=7, N=15, r=4, t=t)
    return qc


def phase_qpe(t, phi):
    """Scalable QPE of the phase gate P(2 pi phi) on one eigenstate qubit with t counting qubits."""
    qc = QuantumCircuit(t + 1, name=f"qpe_t{t}")
    qc.x(t)
    qc.h(range(t))
    for j in range(t):
        qc.cp(2 * math.pi * phi * (2 ** j), j, t)
    qc.compose(QFT(t, inverse=True, do_swaps=True).decompose(), range(t), inplace=True)
    qc.metadata = dict(phi=phi, t=t)
    return qc


def random_circuit(n, depth, seed=SEED):
    """Layers of random U3 on every qubit and CX or CZ on random disjoint pairs."""
    r = np.random.default_rng(seed + 31 * n + depth)
    qc = QuantumCircuit(n, name=f"rand_d{depth}")
    for _ in range(depth):
        for q in range(n):
            qc.u(*r.uniform(0, 2 * math.pi, 3), q)
        perm = r.permutation(n)
        for i in range(0, n - 1, 2):
            a, b = int(perm[i]), int(perm[i + 1])
            (qc.cx if r.integers(2) else qc.cz)(a, b)
    return qc


def partition_heavy(n, layers=8, npart=2):
    """Worst case for the distributed design: non diagonal gates (H, RX) on the top qubits in every layer."""
    qc = QuantumCircuit(n, name="partition_heavy")
    top = list(range(n - npart, n))
    for l in range(layers):
        for q in top:
            qc.h(q); qc.rx(0.1 + 0.2 * l, q)
        qc.cx(top[0], 0)
    return qc


def haar_state(n, seed=SEED):
    r = np.random.default_rng(seed + n)
    v = r.normal(size=1 << n) + 1j * r.normal(size=1 << n)
    return v / np.linalg.norm(v)


def export_qasm(qc, path):
    from qiskit import qasm2
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(qasm2.dumps(qc.decompose(reps=3)))
