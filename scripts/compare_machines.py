#!/usr/bin/env python3
"""Compares the measurements of two hosts configuration by configuration (cross check of the multi card revision).

Author: Nasir Ali, C-DAC Noida.

A configuration is (stage, file, circuit, n, cards, flags, input, partition, per gate, diagonal path, cores). For every
configuration present on both hosts it reports the worst correctness metrics of each host and the ratio of the median
times (engine: T_e2e, submitted design: T_exec, CPU: wall time), and lists every configuration whose ratio lies
outside [1/(1+tol), 1+tol] or that fails correctness on either host.
usage: compare_machines.py <results/raw of host A> <results/raw of host B> [--tol 0.2] [--out report.md]
"""
import argparse, glob, json, os
from collections import defaultdict
import numpy as np

MAXERR = 1e-9     # amplitude error above this is a correctness failure (all reported runs are near 1e-16)


def key(stage, f, r):
    return (stage, os.path.basename(f), r.get("circuit"), r.get("n"), r.get("C", r.get("backend")), r.get("flags", ""),
            r.get("init", "zero"), r.get("part", ""), r.get("per_gate", False), r.get("diag_path", True),
            r.get("pin_cores", 0))


def load(root):
    t, m, src = defaultdict(list), defaultdict(list), {}
    for f in glob.glob(os.path.join(root, "*", "*.json")):
        stage = os.path.basename(os.path.dirname(f)).replace("validation_e8w", "validation")
        if stage.startswith("_"):
            continue
        d = json.load(open(f))
        src[stage] = d.get("meta", {}).get("host")
        for r in d.get("records", []):
            if "circuit" not in r:
                continue
            k = key(stage, f, r)
            if "metrics" in r:
                m[k].append((r["metrics"]["max_abs_err"], r["metrics"]["one_minus_F"]))
            if r.get("warmup"):
                continue
            tm = r.get("timing", {})
            v = tm.get("T_e2e") if "T_e2e" in tm and r.get("design") != "baseline" else tm.get("T_exec", r.get("wall_s"))
            if v is not None:
                t[k].append(v)
    return t, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b")
    ap.add_argument("--tol", type=float, default=0.2)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    ta, ma = load(a.a)
    tb, mb = load(a.b)
    common = sorted(set(ta) & set(tb), key=str)
    only_a, only_b = sorted(set(ta) - set(tb), key=str), sorted(set(tb) - set(ta), key=str)
    lines = [f"# Cross host comparison\n\nA: `{a.a}`  \nB: `{a.b}`\n",
             f"Configurations: {len(common)} on both hosts, {len(only_a)} only on A, {len(only_b)} only on B.\n"]
    ratios, flagged, fails = [], [], []
    for k in common:
        r = np.median(tb[k]) / np.median(ta[k])
        ratios.append(r)
        ea = max((x[0] for x in ma.get(k, [])), default=None)
        eb = max((x[0] for x in mb.get(k, [])), default=None)
        if (ea is not None and ea > MAXERR) or (eb is not None and eb > MAXERR):
            fails.append((k, ea, eb))
        if not (1 / (1 + a.tol) <= r <= 1 + a.tol):
            flagged.append((k, np.median(ta[k]), np.median(tb[k]), r))
    corr_b = [k for k in mb if max(x[0] for x in mb[k]) > MAXERR]
    lines.append(f"Correctness: {sum(len(v) for v in mb.values())} checked instances on B, "
                 f"{len(corr_b)} configurations above {MAXERR:g} max abs error on B.\n")
    if ratios:
        q = np.percentile(ratios, [5, 25, 50, 75, 95])
        lines.append("Time ratio B/A over common configurations: "
                     + ", ".join(f"p{p} {v:.3f}" for p, v in zip((5, 25, 50, 75, 95), q)) + "\n")
    lines.append(f"\n## Correctness failures on either host ({len(fails)})\n")
    lines += [f"- {k}: A {ea}, B {eb}" for k, ea, eb in fails] or ["- none"]
    lines.append(f"\n## Configurations with time ratio outside [{1/(1+a.tol):.3f}, {1+a.tol:.3f}] ({len(flagged)})\n")
    lines.append("| stage | file | circuit | n | C | flags | init | median A (s) | median B (s) | B/A |\n|---|---|---|---|---|---|---|---|---|---|")
    for k, x, y, r in sorted(flagged, key=lambda z: -abs(np.log(z[3]))):
        lines.append(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]} | {k[4]} | {k[5]} | {k[6]} | {x:.4g} | {y:.4g} | {r:.3f} |")
    lines.append(f"\n## Only on A ({len(only_a)})\n")
    lines += [f"- {k[:7]}" for k in only_a[:200]]
    lines.append(f"\n## Only on B ({len(only_b)})\n")
    lines += [f"- {k[:7]}" for k in only_b[:200]]
    txt = "\n".join(lines) + "\n"
    if a.out:
        open(a.out, "w").write(txt)
    print(txt[:3000])


if __name__ == "__main__":
    main()
