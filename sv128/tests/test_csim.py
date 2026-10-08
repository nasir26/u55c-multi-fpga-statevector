"""C simulation of sv128/kernels/sv128_engine.cpp against the NumPy golden model, segment by segment and
slice by slice (each slice with its logical slice id, as each compute unit runs on hardware), then the final
state against Qiskit. usage: test_csim.py <testbench binary>"""
import os, sys, subprocess, tempfile
import numpy as np
from qiskit.circuit.library import QFT
from qiskit.quantum_info import Statevector, random_statevector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "host"), HERE]
from compiler import compile_circuit  # noqa: E402
from model import run_segment, remap, gather_slices, unpermute  # noqa: E402
from test_compiler_model import ghz, grover_like, random_circ, partition_heavy  # noqa: E402

TB = sys.argv[1]
T = tempfile.mkdtemp(prefix="csim128_")


def run_c(seg, state, S, L, sid):
    seg.astype(np.int32).tofile(f"{T}/ins.bin")
    for p in range(S):
        sl = state[p << L:(p + 1) << L]
        sl.astype(np.complex128).tofile(f"{T}/st.bin")
        subprocess.run([TB, f"{T}/ins.bin", f"{T}/st.bin", f"{T}/out.bin", str(sid[p])], check=True)
        sl[:] = np.fromfile(f"{T}/out.bin", dtype=np.complex128)


fails = cases = 0
worst_seg = worst_f = 0.0
for n, L, k in [(8, 6, 6), (9, 6, 5), (10, 7, 7), (11, 8, 8), (12, 9, 9), (13, 11, 11), (12, 10, 4)]:
    circs = [("qft", QFT(n).decompose()), ("ghz", ghz(n)), ("grover", grover_like(n, 1)),
             ("random", random_circ(n, 3, n)), ("partition_heavy", partition_heavy(n, 2))]
    S = 1 << (n - L)
    for name, qc in circs:
        prog, fmap, st = compile_circuit(qc, L, k)
        init = random_statevector(1 << n, seed=n).data
        sm = init.copy(); sc = init.copy()
        sid = list(range(S))
        for kind, payload in prog:
            if kind == "segment":
                run_segment(sm, S, payload, sid); run_c(payload, sc, S, L, sid)
                worst_seg = max(worst_seg, float(np.max(np.abs(sm - sc))))
            elif kind == "relabel":
                sid = [payload[s] for s in sid]
            else:
                sm = remap(gather_slices(sm, L, sid), n, payload)
                sc = remap(gather_slices(sc, L, sid), n, payload)
                sid = list(range(S))
        out = unpermute(gather_slices(sc, L, sid), n, fmap)
        ref = Statevector(init).evolve(qc).data
        err = float(np.max(np.abs(out - ref)))
        inf = 1 - abs(np.vdot(ref, out)) ** 2
        cases += 1
        worst_f = max(worst_f, inf)
        ok = err < 1e-12
        fails += not ok
        print(f"n={n} L={L} k={k} {name:16s} passes={st.n_passes} records={st.n_records} remaps={st.n_remaps} "
              f"relabels={st.n_relabels} max_err={err:.1e} 1-F={inf:.1e} {'OK' if ok else 'FAIL'}", flush=True)
print(f"cases={cases} fails={fails} max|C-model| per segment={worst_seg:.2e} worst 1-F={worst_f:.2e}")
sys.exit(1 if fails else 0)
