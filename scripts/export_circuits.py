#!/usr/bin/env python3
"""Exports every benchmark circuit that appears in results/raw as OpenQASM 2 (results/circuits/), with a sha256 manifest.

Author: Nasir Ali, C-DAC Noida.
The circuits come from bench/circuits.py through the same build() as the experiment drivers (fixed
seeds), so the files are exactly the circuits that were run on the FPGA and on the CPU.
usage: export_circuits.py   (run with the FPGA Python environment, which has Qiskit)
"""
import glob, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path[:0] = [os.path.join(ROOT, "bench"), os.path.join(ROOT, "sv128", "host")]
from run_engine import build  # noqa: E402
from qiskit import qasm2  # noqa: E402

OUT = os.path.join(ROOT, "results", "circuits")


def main():
    pairs = set()
    for f in glob.glob(os.path.join(ROOT, "results", "raw", "**", "*.json"), recursive=True):
        if "_aborted" in f:
            continue
        for r in json.load(open(f)).get("records", []):
            if "circuit" in r and "n" in r:
                pairs.add((r["circuit"], int(r["n"])))
    os.makedirs(OUT, exist_ok=True)
    man = []
    for c, n in sorted(pairs):
        qc = build(c, n)
        try:
            txt = qasm2.dumps(qc)
        except Exception:  # noqa: BLE001  gates without a QASM 2 definition
            txt = qasm2.dumps(qc.decompose(reps=3))
        p = os.path.join(OUT, f"{c}_n{n}.qasm")
        open(p, "w").write(txt)
        man.append(f"{hashlib.sha256(txt.encode()).hexdigest()}  {os.path.basename(p)}")
    open(os.path.join(OUT, "SHA256SUMS"), "w").write("\n".join(man) + "\n")
    print(f"exported {len(man)} circuits to {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
