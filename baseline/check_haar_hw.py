"""Baseline on hardware with Haar random initial states. usage: check_haar_hw.py <xclbin> <n,...>"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "sv128", "host"), os.path.join(HERE, "..", "bench")]
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions

if __name__ == "__main__":
    from qiskit.quantum_info import Statevector
    from dist_v06 import DistV06
    from metrics import compare
    import circuits as C
    d = DistV06(BDF, sys.argv[1])
    for n in [int(x) for x in sys.argv[2].split(",")]:
        init = C.haar_state(n)
        for qc in (C.qft(n), C.random_circuit(n, 4), C.partition_heavy(n, 4), C.grover_kopt(n)):
            for bl in (True, False):
                r = d.run(qc, batch_local=bl, init_state=init)
                m = compare(r["state"], Statevector(init).evolve(qc).data)
                print(json.dumps(dict(c=qc.name, n=n, batch=bl, maxerr=f"{m['max_abs_err']:.2e}",
                                      one_minus_F=f"{m['one_minus_F']:.2e}", route=r["routing"],
                                      T_exec=round(r["timing"]["T_exec"], 4))), flush=True)
    d.close()
