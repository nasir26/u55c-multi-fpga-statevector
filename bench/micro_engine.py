#!/usr/bin/env python3
"""E12 microbenchmarks of the complex128 distributed engine (inputs of the performance model).

Author: Nasir Ali, C-DAC Noida.

  launch   : segment of one pass whose only op is disabled on every slice (engine start, instruction read, finish)
  pass1    : one pass with one op (2 x slice bytes moved per engine) for L = 11 .. Lmax; effective HBM bandwidth
  passm    : one pass with m ops (m = 1, 2, 4, 8, 16, 32, 64) at fixed L: compute bound cost per op
  h2d, d2h : buffer sync bandwidth per card and with all cards concurrently, 4 KiB .. 256 MiB
  exch_dev : device swap of half slices (same card), exch_host: host exchange of half slices across cards
usage: micro_engine.py --xclbin X --cards 4 --engines 16 --swaps 4 --out R.json
"""
import argparse, json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "sv128", "host")]
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions


def seg_ops(L, k, ops):
    """Encoded segment: one pass (m = 0) with the given (t, smask, sval) ops, identity matrices."""
    from isa import MAGIC, OP_MUX2
    I = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    f = np.asarray(I + I, dtype=np.float64).view(np.int32).tolist()
    w = [MAGIC, L, 1, k, 0, 0, 0, 0, 0, 0, 0, len(ops), 0, 0, 0, 0]
    for t, sm, sv in ops:
        w += [OP_MUX2, t, 0, sm, sv, 0, 0, 0] + f
    return (np.asarray(w, dtype=np.int64) & 0xFFFFFFFF).astype(np.uint32).view(np.int32)


def timeit(f, reps):
    out = []
    for _ in range(reps):
        a = time.perf_counter(); f(); out.append(time.perf_counter() - a)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xclbin", required=True)
    ap.add_argument("--cards", type=int, default=4)
    ap.add_argument("--engines", type=int, default=16)
    ap.add_argument("--swaps", type=int, default=4)
    ap.add_argument("--Lmax", type=int, default=24)
    ap.add_argument("--reps", type=int, default=11)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    from runtime import DistSVRuntime, TO, FROM, KMAX
    rt = DistSVRuntime(BDF[:a.cards], a.xclbin, a.engines, a.swaps)
    R = dict(meta=dict(cmd=" ".join(sys.argv), start=time.strftime("%Y-%m-%dT%H:%M:%S%z"), cards=BDF[:a.cards],
                       engines=a.engines), launch={}, pass1={}, passm={}, h2d={}, d2h={}, exch_dev={}, exch_host={})
    P = a.engines
    # launch latency and single pass time vs L
    for L in range(11, a.Lmax + 1):
        rt._alloc(P, L); rt.sid = list(range(len(rt.bos)))
        k = min(KMAX, L)
        rt._upload_ins(seg_ops(L, k, [(0, 0xFFFFFFFF, 0xFFFFFFFF)]))   # disabled everywhere (no slice id matches)
        R["launch"][L] = timeit(rt._run_segment, a.reps)
        rt._upload_ins(seg_ops(L, k, [(0, 0, 0)]))
        R["pass1"][L] = timeit(rt._run_segment, a.reps)
        print(f"L={L} launch={np.median(R['launch'][L]) * 1e6:.1f}us pass1={np.median(R['pass1'][L]) * 1e3:.3f}ms "
              f"HBM={2 * len(rt.bos) * (16 << L) / np.median(R['pass1'][L]) / 1e9:.1f} GB/s (all cards)", flush=True)
        json.dump(R, open(a.out, "w"))
    L = min(a.Lmax, 22)
    rt._alloc(P, L); rt.sid = list(range(len(rt.bos)))
    for m in (1, 2, 4, 8, 16, 32, 64):
        rt._upload_ins(seg_ops(L, min(KMAX, L), [(i % 8, 0, 0) for i in range(m)]))
        R["passm"][m] = timeit(rt._run_segment, a.reps)
        print(f"L={L} ops/pass={m} t={np.median(R['passm'][m]) * 1e3:.3f}ms", flush=True)
    # transfer bandwidth
    for sz in [4 << 10, 64 << 10, 1 << 20, 16 << 20, 64 << 20, 256 << 20]:
        if sz > (16 << L) + (4 << 20):
            rt._alloc(P, max(L, (sz // 16).bit_length() - 1)); rt.sid = list(range(len(rt.bos)))
        one = [g * rt.P for g in range(rt.C)]          # first buffer of every card
        R["h2d"][sz] = dict(one_card=timeit(lambda: rt.bos[0].sync(TO, sz, 0), a.reps),
                            all_cards=timeit(lambda: rt.pool_map(lambda g: rt.bos[g].sync(TO, sz, 0), one), a.reps))
        R["d2h"][sz] = dict(one_card=timeit(lambda: rt.bos[0].sync(FROM, sz, 0), a.reps),
                            all_cards=timeit(lambda: rt.pool_map(lambda g: rt.bos[g].sync(FROM, sz, 0), one), a.reps))
        print(f"sync {sz >> 10} KiB: h2d {sz / np.median(R['h2d'][sz]['one_card']) / 1e9:.2f} GB/s one card, "
              f"{rt.C * sz / np.median(R['h2d'][sz]['all_cards']) / 1e9:.2f} GB/s all; d2h "
              f"{sz / np.median(R['d2h'][sz]['one_card']) / 1e9:.2f} / {rt.C * sz / np.median(R['d2h'][sz]['all_cards']) / 1e9:.2f}",
              flush=True)
        json.dump(R, open(a.out, "w"))
    # exchanges: slice bit 0 (same card, device swap) and the top slice bit (across cards, host)
    for L in (16, 20, min(a.Lmax, 24)):
        rt._alloc(P, L); rt.sid = list(range(len(rt.bos)))
        for kind, j in (("exch_dev", 0), ("exch_host", (rt.C * P).bit_length() - 2)):
            if kind == "exch_host" and rt.C == 1:
                continue
            T = {k: 0.0 for k in ("T_exch_dev", "T_exch_host", "T_exch_host_d2h", "T_exch_host_copy", "T_exch_host_h2d")}
            T.update(bytes_exch_dev=0, bytes_pcie_exch=0, n_exch_dev=0, n_exch_host=0, n_exch_cross_card=0)
            ts = timeit(lambda: rt._exchange(j, L - 1, T), a.reps)
            R[kind][L] = dict(t=ts, detail=dict(T))
            print(f"{kind} L={L}: {np.median(ts) * 1e3:.2f} ms", flush=True)
        json.dump(R, open(a.out, "w"))
    R["meta"]["end"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    json.dump(R, open(a.out, "w"))


if __name__ == "__main__":
    main()
