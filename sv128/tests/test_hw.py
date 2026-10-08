"""First hardware validation of the complex128 engine: 1, 2, 4 cards, slice paths on and off, zero and Haar inputs,
against Qiskit Statevector. usage: test_hw.py <xclbin> <engines> <swaps> <n,...>"""
import os, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "host"), os.path.join(HERE, "..", "..", "bench")]
import numpy as np
from qiskit.quantum_info import Statevector
from runtime import DistSVRuntime
from metrics import compare
import circuits as C
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions
xcl, ne, ns = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
nlist = [int(x) for x in sys.argv[4].split(",")]
fails = 0
for nc in (1, 2, 4):
    rt = DistSVRuntime(BDF[:nc], xcl, ne, ns)
    for n in nlist:
        init = C.haar_state(n)
        for name, qc in (("qft", C.qft(n)), ("ghz", C.ghz_chain(n)), ("rand", C.random_circuit(n, 4)),
                         ("ph", C.partition_heavy(n, 4)), ("grover", C.grover_kopt(min(n, 10)) if n <= 10 else None)):
            if qc is None:
                continue
            for fl in ((True, True, True, "auto"), (False, False, False, False)):
                for iv in (None, init):
                    r = rt.run(qc, shots=16, f1=fl[0], f2=fl[1], f3=fl[2], f4=fl[3], init_state=iv)
                    ref = (Statevector(iv) if iv is not None else Statevector.from_int(0, 2 ** n)).evolve(qc).data
                    m = compare(r["state"], ref)
                    ok = bool(m["max_abs_err"] < 1e-12 and np.isfinite(m["max_abs_err"]))
                    fails += not ok
                    T = r["timing"]
                    print(json.dumps(dict(C=nc, n=n, P=r["P"], L=r["L"], c=name, f=int(fl[0]), init="haar" if iv is not None else "zero",
                                          maxerr=f"{m['max_abs_err']:.2e}", ok=ok, e2e=round(T["T_e2e"], 4), kern=round(T["T_kernel"], 4),
                                          exch_dev=T["n_exch_dev"], exch_host=T["n_exch_host"], swap_ok=[bool(x) for x in rt.swap_ok])), flush=True)
print("FAILS", fails)
