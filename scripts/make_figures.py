#!/usr/bin/env python3
"""Generates every figure of the revised manuscript from results/raw (no hand typed data).

Author: Nasir Ali, C-DAC Noida.
Figures (paper/revised/figures/*.pdf):
  fig_breakdown  per phase time of the revised engine, four cards (R1.E)
  fig_scaling    end to end time and speedup on 1, 2, 4 cards (R1.C)
  fig_ablation   time with the slice paths on and off (R1.D, R2.3)
  fig_cpu        FPGA end to end time against Qiskit Statevector and Aer on the same host (R2.2)
  fig_model      submitted design: measured QFT time against the microbenchmark model (R2.1)
  fig_bytes      PCIe bytes per circuit for the baseline and the revised engine (R1.m.3)
Statistics: median of the timed repetitions (warm up excluded), bars or whiskers show the interquartile range.
"""
import glob, json, os, sys
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RAW = os.path.join(ROOT, "results", "raw")
OUT = os.path.join(ROOT, "figures")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 9, "figure.dpi": 150, "savefig.bbox": "tight", "pdf.fonttype": 42})
C3 = {1: "#4c72b0", 2: "#dd8452", 4: "#55a868"}


def load(pattern):
    out = []
    for f in sorted(glob.glob(os.path.join(RAW, pattern))):
        d = json.load(open(f))
        if d.get("meta", {}).get("mock"):
            raise SystemExit(f"mock data in results: {f}")
        out += [dict(r, _file=os.path.basename(f)) for r in d.get("records", []) if not r.get("warmup")]
    return out


def med(v):
    v = np.asarray(v, float)
    return np.median(v), np.percentile(v, 25), np.percentile(v, 75)


def save(fig, name):
    fig.savefig(os.path.join(OUT, name + ".pdf"))
    fig.savefig(os.path.join(OUT, name + ".png"))
    plt.close(fig)
    print("wrote", name)


def fig_breakdown(eng):
    rs = [r for r in eng if r.get("C") == 4 and r.get("flags", "").startswith("111")]
    keys = [("T_compile", "compile"), ("T_h2d", "upload"), ("T_kernel", "kernel"), ("T_exch_dev", "exchange in card"),
            ("T_exch_host", "exchange across cards"), ("T_local_remap", "local remap"), ("T_d2h", "read back"), ("T_post", "sampling")]
    sel = sorted({(r["circuit"], r["n"]) for r in rs if r["n"] in (20, 24, 28, 30)})
    if not sel:
        return
    fig, ax = plt.subplots(figsize=(7, 3.2))
    bottom = np.zeros(len(sel))
    for k, lab in keys:
        vals = np.array([np.median([r["timing"][k] for r in rs if (r["circuit"], r["n"]) == s]) for s in sel])
        ax.bar(range(len(sel)), vals, bottom=bottom, label=lab)
        bottom += vals
    ax.set_xticks(range(len(sel))); ax.set_xticklabels([f"{c}\n{n}" for c, n in sel], fontsize=7)
    ax.set_yscale("log"); ax.set_ylabel("time (s), median"); ax.legend(fontsize=6, ncol=2)
    save(fig, "fig_breakdown")


def fig_scaling(sc):
    rs = [r for r in sc if r.get("flags", "").startswith("111")]
    circs = sorted({r["circuit"] for r in rs})
    if not circs:
        return
    fig, axs = plt.subplots(1, len(circs), figsize=(7, 2.6), sharey=True)
    for ax, c in zip(np.atleast_1d(axs), circs):
        for C in (1, 2, 4):
            ns = sorted({r["n"] for r in rs if r["circuit"] == c and r["C"] == C})
            m = [med([r["timing"]["T_e2e"] for r in rs if r["circuit"] == c and r["C"] == C and r["n"] == n]) for n in ns]
            if ns:
                ax.errorbar(ns, [x[0] for x in m], yerr=[[x[0] - x[1] for x in m], [x[2] - x[0] for x in m]],
                            marker="o", ms=3, color=C3[C], label=f"{C} card" + ("s" if C > 1 else ""))
        ax.set_yscale("log"); ax.set_title(c, fontsize=8); ax.set_xlabel("$n$")
    np.atleast_1d(axs)[0].set_ylabel("$T_{e2e}$ (s)"); np.atleast_1d(axs)[0].legend(fontsize=6)
    save(fig, "fig_scaling")


def fig_ablation(ab):
    if not ab:
        return
    names = {"111a": "all on", "011a": "F1 off", "101a": "F2 off", "110a": "F3 off", "1110": "F4 off", "0000": "all off"}
    rs = [r for r in ab if r["n"] == max(x["n"] for x in ab) and r["flags"] in names]
    circs = sorted({r["circuit"] for r in rs})
    fig, ax = plt.subplots(figsize=(7, 2.8))
    w = 0.8 / len(names)
    for i, (fl, lab) in enumerate(names.items()):
        vals = [np.median([r["timing"]["T_e2e"] for r in rs if r["circuit"] == c and r["flags"] == fl] or [np.nan]) for c in circs]
        ax.bar(np.arange(len(circs)) + i * w, vals, w, label=lab)
    ax.set_xticks(np.arange(len(circs)) + 0.4 - w / 2); ax.set_xticklabels(circs, fontsize=7)
    ax.set_yscale("log"); ax.set_ylabel("$T_{e2e}$ (s)"); ax.legend(fontsize=6, ncol=3)
    ax.set_title(f"four cards, n = {rs[0]['n'] if rs else ''}", fontsize=8)
    save(fig, "fig_ablation")


def fig_cpu(eng, cpu):
    if not cpu:
        return
    circs = ["qft", "ghz", "rand10"]
    fig, axs = plt.subplots(1, 3, figsize=(7, 2.6), sharey=True)
    for ax, c in zip(axs, circs):
        for be, lab, st in (("sv", "Qiskit Statevector (1 thread)", "s-"), ("aer1", "Aer, 1 thread", "^-"), ("aer", "Aer, all threads", "v-")):
            ns = sorted({r["n"] for r in cpu if r["circuit"] == c and r["backend"] == be})
            ax.plot(ns, [np.median([r["wall_s"] for r in cpu if r["circuit"] == c and r["backend"] == be and r["n"] == n]) for n in ns],
                    st, ms=3, label=lab)
        ns = sorted({r["n"] for r in eng if r["circuit"] == c and r.get("C") == 4 and r.get("flags", "").startswith("111")})
        ax.plot(ns, [np.median([r["timing"]["T_e2e"] for r in eng if r["circuit"] == c and r.get("C") == 4 and r["n"] == n
                                and r.get("flags", "").startswith("111")]) for n in ns], "o-k", ms=3, label="FPGA, 4 cards")
        ax.set_yscale("log"); ax.set_title(c, fontsize=8); ax.set_xlabel("$n$")
    axs[0].set_ylabel("time (s), median"); axs[0].legend(fontsize=5)
    save(fig, "fig_cpu")


def fig_model(bl):
    import model_v06
    mc = model_v06.load_micro()
    rs = [r for r in bl if r.get("circuit") == "qft" and not r.get("per_gate") and r.get("init", "zero") == "zero"
          and r["_file"] in ("v06_batched.json", "v06_large.json")]
    if mc is None or not rs:
        return
    ns = sorted({r["n"] for r in rs})
    meas = [med([r["timing"]["T_exec"] for r in rs if r["n"] == n]) for n in ns]
    pred = [model_v06.predict(mc, n - (r0["C"].bit_length() - 1), r0["routing"])
            for n in ns for r0 in [next(r for r in rs if r["n"] == n)]]
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    ax.errorbar(ns, [x[0] for x in meas], yerr=[[x[0] - x[1] for x in meas], [x[2] - x[0] for x in meas]],
                fmt="o-", ms=3, color="k", label="measured")
    pn = [(n, p) for n, p in zip(ns, pred) if p is not None]
    ax.plot([x[0] for x in pn], [x[1] for x in pn], "s--", ms=3, color=C3[2], label="model (microbenchmarks)")
    ax.set_yscale("log"); ax.set_xlabel("$n$"); ax.set_ylabel("execution time (s)"); ax.legend(fontsize=6)
    ax.set_title("submitted design, QFT, four cards", fontsize=8)
    save(fig, "fig_model")


def fig_bytes(eng, bl):
    """Total PCIe bytes per run: state upload and read back plus every exchange and remap (and instructions for the engine)."""
    circs = ["qft", "ghz", "rand10"]
    fig, axs = plt.subplots(1, 3, figsize=(7, 2.4), sharey=True)
    for ax, c in zip(axs, circs):
        e = [r for r in eng if r["circuit"] == c and r.get("C") == 4 and r.get("flags", "").startswith("111")]
        ns = sorted({r["n"] for r in e})
        tb = lambda r: 2 * 16 * (1 << r["n"]) + sum(r["timing"][k] for k in ("bytes_pcie_exch", "bytes_pcie_local_remap", "bytes_pcie_ins"))
        ax.plot(ns, [np.median([tb(r) for r in e if r["n"] == n]) for n in ns], "o-", ms=3, color=C3[4], label="revised engine")
        b = [r for r in bl if r["circuit"] == c and not r.get("per_gate") and r.get("init", "zero") == "zero"
          and r["_file"] in ("v06_batched.json", "v06_large.json")]
        nb = sorted({r["n"] for r in b})
        ax.plot(nb, [np.median([r["bytes"]["pcie_d2h"] + r["bytes"]["pcie_h2d"] for r in b if r["n"] == n]) for n in nb],
                "s-", ms=3, color=C3[2], label="submitted design")
        ax.set_yscale("log"); ax.set_title(c, fontsize=8); ax.set_xlabel("$n$")
    axs[0].set_ylabel("PCIe bytes per run"); axs[0].legend(fontsize=6)
    save(fig, "fig_bytes")


def fig_architecture():
    """Block diagram of the main build, drawn from builds/sv128_e8w/link.cfg (engines, PCs, SLRs, exchange units)."""
    import re
    from matplotlib.patches import FancyBboxPatch
    cfg = open(os.path.join(ROOT, "builds", "sv128_e8w", "link.cfg")).read()
    eng = {int(m[0]): (int(m[1]), int(m[2])) for m in re.findall(r"sp=sv128_engine_(\d+)\.st:HBM\[(\d+):(\d+)\]", cfg)}
    slr = {int(m[0]): int(m[1]) for m in re.findall(r"slr=sv128_engine_(\d+):SLR(\d)", cfg)}
    nsw = int(re.search(r"nk=sv_swap:(\d+)", cfg).group(1))
    fig, ax = plt.subplots(figsize=(7, 4.4))
    ax.set_xlim(0, 100); ax.set_ylim(0, 64); ax.axis("off")

    def box(x, y, w, h, txt, fc="#ffffff", ec="k", fs=7, lw=0.8):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.2,rounding_size=0.8", fc=fc, ec=ec, lw=lw))
        if txt:
            ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=fs)
    # host
    box(2, 50, 96, 12, "", fc="#f2f2f2")
    ax.text(4, 60, "Host (2 sockets, 128 cores)", fontsize=7, va="center", weight="bold")
    box(4, 51.5, 20, 6, "compiler\nF1 to F4, passes, remaps", fs=6)
    box(27, 51.5, 20, 6, "runtime\nslice table (F3)", fs=6)
    box(50, 51.5, 22, 6, "host memory\ncross card exchange", fs=6)
    box(75, 51.5, 21, 6, "reference check\n(outside timing)", fs=6)
    # cards
    xs = [2, 26.5, 51, 75.5]
    for i, (x, lab) in enumerate(zip(xs, ["card 0 (bus 01)", "card 1 (bus 21)", "card 2 (bus 41)", "card 3 (bus a1)"])):
        ax.annotate("", xy=(x + 11, 40.5), xytext=(x + 11, 50), arrowprops=dict(arrowstyle="<->", lw=0.9))
        ax.text(x + 12, 45.5, "PCIe Gen3 x16", fontsize=5.5, va="center")
        box(x, 31, 22.5, 9, f"{lab}\nslice qubits\nselect the card" if i else f"{lab}\nexpanded below", fc="#e8f0fa", fs=6)
    # expanded card 0
    box(2, 1, 96, 27, "", fc="#e8f0fa")
    ax.text(4, 26, "Alveo U55C, 16 GiB HBM2 = 32 pseudo channels (PC) of 512 MiB, 300 MHz", fontsize=6.5, weight="bold", va="center")
    cols = {0: "#4c72b0", 1: "#dd8452", 2: "#55a868"}
    w = 11
    for e in sorted(eng):
        x = 4 + (e - 1) * 11.7
        lo, hi = eng[e]
        box(x, 15, w, 8, f"engine {e}\nSLR{slr[e]}\nKMAX 11\n2 pairs/cycle", fc="#ffffff", ec=cols[slr[e]], fs=5.2, lw=1.2)
        for j, pc in enumerate(range(lo, hi + 1)):
            box(x + 0.2 + j * 2.75, 9.5, 2.3, 3.5, "", fc="#fff7d6", fs=4)
            ax.text(x + 1.35 + j * 2.75, 11.25, str(pc), fontsize=4.2, ha="center", va="center")
        ax.annotate("", xy=(x + w / 2, 13.2), xytext=(x + w / 2, 14.8), arrowprops=dict(arrowstyle="<->", lw=0.6))
    ax.text(50, 7.5, "HBM pseudo channels 0 to 31: slice amplitudes and the instruction segment of each engine",
            fontsize=5.8, ha="center", va="center")
    box(4, 2, 92, 4, f"{nsw} exchange units (sv_swap), each with two ports reaching all 32 PCs: half slice copies inside the card",
        fc="#ffffff", fs=5.8)
    ax.text(4, 2, "", fontsize=1)
    save(fig, "fig_architecture")


FIGURES = ["fig_architecture", "fig_breakdown", "fig_scaling", "fig_ablation", "fig_cpu", "fig_model", "fig_bytes"]


def placeholders():
    """A red PENDING panel for every figure without data yet (draft builds only; the final gate rejects PENDING)."""
    for name in FIGURES:
        if not os.path.exists(os.path.join(OUT, name + ".pdf")):
            fig, ax = plt.subplots(figsize=(4, 1.2)); ax.axis("off")
            ax.text(0.5, 0.5, f"PENDING: {name} (no data yet)", color="red", ha="center", va="center")
            fig.savefig(os.path.join(OUT, name + ".pdf")); plt.close(fig)
            open(os.path.join(OUT, name + ".pending"), "w").write("placeholder\n")
            print("placeholder", name)


def main():
    for f in glob.glob(os.path.join(OUT, "*.pending")):
        os.remove(f); os.remove(f[:-len(".pending")] + ".pdf")
    fig_architecture()
    eng = load("main/*.json")
    fig_breakdown(eng)
    fig_scaling(load("scaling/*.json"))
    fig_ablation(load("ablation/*.json"))
    fig_cpu(eng, load("cpu/*.json"))
    bl = load("baseline/*.json")
    fig_model(bl)
    fig_bytes(eng, bl)
    placeholders()


if __name__ == "__main__":
    main()
