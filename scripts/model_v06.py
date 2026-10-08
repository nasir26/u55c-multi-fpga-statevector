#!/usr/bin/env python3
"""Microbenchmark model of the submitted design (v06 kernel), used by make_tables.py and make_figures.py.

Author: Nasir Ali, C-DAC Noida.

No parameter is fitted to the circuit timings. Every term is a median from results/raw/micro/baseline_v06_4c.json
and every count is the routing counter that the baseline driver recorded for the circuit:

  T_exec(n) = L * (g1(l) + q) + (D + X) * (c(l) + d(l) + q) + X * 3 * b

  l     local qubits per card, n minus log2(C)
  L     local kernel launches (batched segments), D partition diagonal gates, X exchanges
  g1    one kernel launch with one gate on l qubits (gate upload, start, wait)
  c, d  collect (8 bank read and de interleave) and distribute (interleave and 8 bank write) of one slice
  q     coordinator to worker command round trip (all cards)
  b     one barrier round across the card processes
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


def predict(micro, l, routing):
    """Model execution time for one run with local width l and the recorded routing counters, or None."""
    if micro is None or l not in micro["g1"]:
        return None
    L, D, X = routing.get("launches", 0), routing.get("diag", 0), routing.get("exchange", 0)
    q = micro["q"]
    return (L * (micro["g1"][l] + q) + (D + X) * (micro["collect"][l] + micro["distribute"][l] + q)
            + X * 3 * micro["b"])


if __name__ == "__main__":
    mc = load_micro()
    if mc is None:
        raise SystemExit("no microbenchmark data yet")
    for l in sorted(mc["g1"]):
        print(f"l={l:2d} g1={mc['g1'][l]*1e3:8.3f} ms collect={mc['collect'][l]*1e3:8.3f} ms distribute={mc['distribute'][l]*1e3:8.3f} ms")
    print(f"q={mc['q']*1e6:.0f} us b={mc['b']*1e6:.0f} us")
