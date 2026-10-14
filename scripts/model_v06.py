#!/usr/bin/env python3
"""Microbenchmark model of the submitted design (v06 kernel), used by make_tables.py and make_figures.py.

Author: Nasir Ali, C-DAC Noida.

No parameter is fitted to the circuit timings. Every time is a median from results/raw/micro/baseline_v06_4c.json,
every count comes from the routing of the circuit (results/v06_op_counts.json, replayed from baseline/dist_v06.py and
checked against the routing counters recorded on hardware), and the relative cost of the native operations comes
from the loop structure of the kernel source (single qubit and CZ loops: N/2 x II 16 and N x II 8 cycles; CX loop:
N x II 16 cycles, twice as long):

  T_exec(n) = (o1 + 2 x + z) * s(l) + K * (a(l) + q) + (D + X) * (c(l) + d(l) + q) + X * 3 * b

  l          local qubits per card, n minus log2(C)
  o1, x, z   native single qubit, CX and CZ operations in all local segments
  K          kernel launches; D partition diagonal gates; X exchanges
  s(l)       one native single qubit operation: g1(l) minus a(l), with g1 one launch with one gate (gate upload,
             start, sweep, wait) and a an empty launch
  c, d       collect (8 bank read and de interleave) and distribute (interleave and 8 bank write) of one slice
  q          coordinator to worker command round trip (all cards); b one barrier round across the card processes
Host arithmetic on the collected slices is not part of the model; the difference to the measurement is reported.
"""
import json, os
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
MICRO = os.path.join(ROOT, "results", "raw", "micro", "baseline_v06_4c.json")


def load_micro(path=MICRO):
    if not os.path.exists(path):
        return None
    m = json.load(open(path))
    c0 = m["card0"]
    med = lambda d: {int(k): float(np.median(v)) for k, v in d.items()}
    return dict(g1=med(c0["gate1"]), launch=med(c0["launch"]), collect=med(c0["collect"]),
                distribute=med(c0["distribute"]), q=float(np.median(m["queue_rtt"])),
                b=float(np.median(m["barrier_round"])), cards=len(m["meta"]["cards"]))


OPS = os.path.join(ROOT, "results", "v06_op_counts.json")


def load_ops(path=OPS):
    return json.load(open(path))["counts"] if os.path.exists(path) else None


def predict(micro, l, ops):
    """Model execution time for one run with local width l and the native operation counts ops, or None."""
    if micro is None or ops is None or l not in micro["g1"] or l not in micro["launch"]:
        return None
    s1 = micro["g1"][l] - micro["launch"][l]
    q = micro["q"]
    return ((ops["op1"] + 2 * ops["cx"] + ops["cz"]) * s1 + ops["launches"] * (micro["launch"][l] + q)
            + (ops["diag"] + ops["exchange"]) * (micro["collect"][l] + micro["distribute"][l] + q)
            + ops["exchange"] * 3 * micro["b"])


if __name__ == "__main__":
    mc = load_micro()
    if mc is None:
        raise SystemExit("no microbenchmark data yet")
    for l in sorted(mc["g1"]):
        print(f"l={l:2d} g1={mc['g1'][l]*1e3:8.3f} ms collect={mc['collect'][l]*1e3:8.3f} ms distribute={mc['distribute'][l]*1e3:8.3f} ms")
    print(f"q={mc['q']*1e6:.0f} us b={mc['b']*1e6:.0f} us")
