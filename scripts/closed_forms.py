#!/usr/bin/env python3
"""Closed form quantities used by the error ledger and the manuscript (no measured values here).

Writes results/closed_forms.json:
  grover   : analytic success probability P(k) = sin^2((2k+1) theta), theta = asin(2^(-n/2)), for the k used in the
             submitted Table 6, for k_opt = floor(pi / (4 theta)) and for the submitted formula ceil(pi/4 sqrt(2^n))
  qft      : gate counts n H + n(n-1)/2 CP + floor(n/2) SWAP, and the routing of the submitted design (top two qubits
             partition qubits) counted gate by gate
  capacity : statevector bytes for complex64 and complex128
  kernel   : streaming rate of a single issue kernel at II = 16, 258.5 MHz, 64 bytes per amplitude pair
"""
import json, math, os

out = {}
G = {}
for n, k_used in ((4, 3), (6, 6), (8, 13), (10, 25), (12, None)):
    th = math.asin(2 ** (-n / 2))
    k_opt = math.floor(math.pi / (4 * th))
    k_formula = math.ceil(math.pi / 4 * math.sqrt(2 ** n))
    P = lambda k: math.sin((2 * k + 1) * th) ** 2
    G[n] = dict(k_used=k_used, P_k_used=(P(k_used) if k_used is not None else None), k_opt=k_opt, P_k_opt=P(k_opt),
                k_submitted_formula=k_formula, P_k_submitted_formula=P(k_formula),
                P_max_over_k=max(P(k) for k in range(0, 4 * k_opt + 4)))
out["grover"] = G


def qft_routing(n, npb=2):
    """Gate by gate routing of the textbook QFT (H, CP chain, final SWAPs) under the submitted three path scheme."""
    part = set(range(n - npb, n))
    local = diag = exch = 0
    gates = []
    for i in range(n):
        gates.append(("h", (i,)))
        for j in range(i + 1, n):
            gates.append(("cp", (j, i)))
    for i in range(n // 2):
        gates.append(("swap", (i, n - 1 - i)))
    for g, q in gates:
        touches = any(x in part for x in q)
        if not touches:
            local += 1
        elif g == "cp":
            diag += 1
        else:
            exch += 1
    return dict(total=len(gates), local=local, diagonal=diag, exchange=exch,
                formula_total=n * (n + 1) // 2 + n // 2, submitted_formula_total=n * (n + 1) // 2)


out["qft"] = {n: qft_routing(n) for n in range(4, 31, 2)}
out["capacity_bytes"] = {n: dict(c64=(1 << n) * 8, c128=(1 << n) * 16) for n in range(20, 33)}
f, ii = 258.5e6, 16
out["kernel_single_issue"] = dict(II=ii, f_hz=f, bytes_per_pair=64,
                                  pairs_per_s=f / ii, bytes_per_s=f / ii * 64,
                                  t_1q_gate_s_per_card={n: (2 ** (n - 3)) * ii / f for n in (20, 24, 28)})
here = os.path.dirname(os.path.abspath(__file__))
dst = os.path.join(here, "..", "results", "closed_forms.json")
json.dump(out, open(dst, "w"), indent=1)
for n, g in G.items():
    print(f"grover n={n}: k_used={g['k_used']} P={g['P_k_used']} k_opt={g['k_opt']} P_opt={g['P_k_opt']:.6f} "
          f"formula k={g['k_submitted_formula']} P={g['P_k_submitted_formula']:.6f} Pmax={g['P_max_over_k']:.6f}")
for n in (12, 18, 20):
    print("qft", n, out["qft"][n])
print("kernel", {k: v for k, v in out["kernel_single_issue"].items() if k != "t_1q_gate_s_per_card"},
      out["kernel_single_issue"]["t_1q_gate_s_per_card"])
