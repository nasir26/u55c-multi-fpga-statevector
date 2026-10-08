"""Correctness check of the baseline distributed design on hardware. usage: check_hw.py <xclbin> <C> <n,...>"""
import os, sys, json, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.quantum_info import Statevector
from dist_v06 import DistV06
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sv128", "host"))
from metrics import compare
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions


def ghz(n):
    qc = QuantumCircuit(n); qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return qc


if __name__ == "__main__":
    xclbin, C = sys.argv[1], int(sys.argv[2])
    ns = [int(x) for x in sys.argv[3].split(",")]
    d = DistV06(BDF[:C], xclbin)
    for n in ns:
        for name, qc in (("qft", QFT(n).decompose()), ("ghz", ghz(n))):
            r = d.run(qc)
            ref = Statevector(qc).data
            m = compare(r["state"], ref)
            print(json.dumps(dict(name=name, n=n, C=C, **{k: float(f"{v:.3e}") for k, v in m.items()}, routing=r["routing"],
                                  timing={k: round(v, 4) for k, v in r["timing"].items()})), flush=True)
    d.close()
