#!/usr/bin/env python3
"""Native kernel operation counts of the submitted design (v06) per circuit, input of scripts/model_v06.py.

Author: Nasir Ali, C-DAC Noida.

Replays the routing and batching of baseline/dist_v06.py (DistV06.run) for every circuit and width of the baseline
campaign without hardware: gates are routed with dist_v06.route, consecutive local gates form one segment, and each
segment is lowered with the v06 host's own _lower_to_kernel_basis and encoded with its _encode_gates, exactly as the
card workers do. For every circuit the result lists the native operations per type (single qubit, CX, CZ), the kernel
launches (segments split at KERNEL_MAX_GATES), and the partition diagonal and exchange gates.
usage: v06_op_counts.py   (FPGA Python environment)   -> results/v06_op_counts.json
"""
import json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
B = os.path.join(ROOT, "baseline")
sys.path[:0] = [B, os.path.join(ROOT, "bench"), os.path.join(ROOT, "sv128", "host")]
import fpga_simulator_v06 as v06  # noqa: E402
from dist_v06 import circuit_to_gates, route  # noqa: E402
from run_engine import build  # noqa: E402

CIRCUITS = {"qft": [4, 8, 12, 14, 16, 18, 20, 22, 24, 26, 28], "ghz": [4, 8, 12, 14, 16, 18, 20, 22, 24, 26, 28],
            "bell": [4, 8, 12, 14, 16, 18, 20, 22], "qft_iqft": [4, 8, 12, 14, 16, 18, 20, 22],
            "rand10": [4, 8, 12, 14, 16, 18, 20, 22], "partition_heavy": [4, 8, 12, 14, 16, 18, 20, 22]}
C = 4
TWO_Q = {"cx": "cx", "cnot": "cx", "cz": "cz"}


def counts(name, n):
    nlq = n - (C.bit_length() - 1)
    gates, _ = circuit_to_gates(build(name, n))
    enc = v06.QuantumFPGACircuit.__new__(v06.QuantumFPGACircuit)
    seg, out = [], dict(op1=0, cx=0, cz=0, launches=0, segments=0, diag=0, exchange=0, local_gates=0)

    def flush():
        if not seg:
            return
        lowered = v06._lower_to_kernel_basis(list(seg))
        _, nt, res = enc._encode_gates(lowered)
        for g in res:
            nm = g[0].lower() if isinstance(g[0], str) else g[0]
            out[TWO_Q.get(nm, "op1")] += 1
        out["launches"] += -(-nt // v06.KERNEL_MAX_GATES)
        out["segments"] += 1
        seg.clear()
    for nm, qs, ps, M in gates:
        r = route(nm, qs, M, nlq)
        if r == "local":
            seg.append((nm, qs, ps if ps else None)); out["local_gates"] += 1
            continue
        flush()
        out[r] += 1
    flush()
    return out


def main():
    res = {}
    for c, ns in CIRCUITS.items():
        for n in ns:
            res[f"{c}:{n}"] = counts(c, n)
            print(c, n, res[f"{c}:{n}"], flush=True)
    dst = os.path.join(ROOT, "results", "v06_op_counts.json")
    json.dump(dict(cards=C, kernel_max_gates=v06.KERNEL_MAX_GATES, counts=res), open(dst, "w"), indent=1)
    print("wrote", os.path.relpath(dst, ROOT))


if __name__ == "__main__":
    main()
