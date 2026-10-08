#!/usr/bin/env python3
"""Experiment driver for the submitted design (v06 or v07 kernel), same record format as bench/run_engine.py.

Author: Nasir Ali, C-DAC Noida.

usage: run_baseline.py --xclbin X --cards 4 --circuits qft,ghz --ns 12,16,20 --reps 6 [--per-gate] [--init haar] --out R.json
"""
import argparse, hashlib, json, os, socket, subprocess, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "sv128", "host"), os.path.join(HERE, "..", "bench")]
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xclbin", required=True)
    ap.add_argument("--kernel-version", default="v06")
    ap.add_argument("--cards", type=int, default=4)
    ap.add_argument("--circuits", required=True)
    ap.add_argument("--ns", required=True)
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--per-gate", action="store_true", help="one dispatch per local gate (as described in the submission)")
    ap.add_argument("--init", default="zero", choices=["zero", "haar"])
    ap.add_argument("--no-diag", action="store_true", help="route partition diagonal gates through the exchange path (ablation, R1.D)")
    ap.add_argument("--ref-max", type=int, default=30)
    ap.add_argument("--pin-cores", type=int, default=0, help="restrict the host process (and its threads and workers) to cores 0 .. N-1")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.pin_cores:
        os.sched_setaffinity(0, set(range(a.pin_cores)))
    from dist_v06 import DistV06
    from metrics import compare
    from run_engine import build, reference
    import circuits as Cm
    d = DistV06(BDF[:a.cards], a.xclbin)
    git = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    meta = dict(design="submitted (baseline)", kernel=a.kernel_version, cmd=" ".join(sys.argv),
                start=time.strftime("%Y-%m-%dT%H:%M:%S%z"), host=socket.gethostname(), git=git,
                xclbin=os.path.abspath(a.xclbin), xclbin_sha256=sha(a.xclbin), bdfs=BDF[:a.cards],
                per_gate=a.per_gate, init=a.init, seed=Cm.SEED, pin_cores=a.pin_cores, diag_path=not a.no_diag)
    recs = []
    sys.path.insert(0, os.path.join(HERE, "..", "bench"))
    import fpga_power

    def guard():
        """Wait while any card is at or above 88 C (FPGA); stop at the abort limits (90 C FPGA, 85 C HBM)."""
        t0 = time.perf_counter()
        while True:
            t = {b: (fpga_power._r(fpga_power.xmc_dir(b), "xmc_fpga_temp"), fpga_power._r(fpga_power.xmc_dir(b), "xmc_hbm_temp"))
                 for b in BDF[:a.cards]}
            if any(f >= fpga_power.FPGA_LIMIT_C or h >= fpga_power.HBM_LIMIT_C for f, h in t.values()):
                d.close()
                raise SystemExit(f"card at the abort limit: {t}")
            if all(f < 88 for f, h in t.values()) or time.perf_counter() - t0 > 1800:
                return time.perf_counter() - t0
            time.sleep(10)
    for name in a.circuits.split(","):
        for n in [int(x) for x in a.ns.split(",")]:
            qc = build(name, n)
            init = Cm.haar_state(n) if a.init == "haar" else None
            ref = None
            cool_s = guard()
            for rep in range(a.reps):
                r = d.run(qc, batch_local=not a.per_gate, init_state=init, diag_path=not a.no_diag)
                pc = r["per_card"]
                agg = {k: max(pc[c][0][k] for c in pc) for k in pc[0][0]}          # slowest card per phase
                byt = {k: sum(pc[c][1][k] for c in pc) for k in pc[0][1]}          # all cards
                rec = dict(circuit=name, n=n, C=a.cards, design="baseline", kernel=a.kernel_version, per_gate=a.per_gate,
                           init=a.init, diag_path=not a.no_diag, pin_cores=a.pin_cores, rep=rep, warmup=rep == 0, timing=r["timing"], per_card_max=agg, bytes=byt,
                           routing=r["routing"], T_setup=r["T_setup"], cool_wait_s=cool_s if rep == 0 else 0.0, meta_qc=getattr(qc, "metadata", None) or {})
                if rep == a.reps - 1 and n <= a.ref_max:
                    t0 = time.perf_counter()
                    if ref is None:
                        ref, src = reference(qc, init)
                    rec["metrics"] = compare(r["state"], ref); rec["reference"] = src
                    rec["T_reference"] = time.perf_counter() - t0
                    if name == "grover":
                        rec["P_target"] = float(abs(r["state"][qc.metadata["marked"]]) ** 2)
                recs.append(rec)
                print(f"baseline {name:12s} n={n:2d} rep={rep} e2e={r['timing']['T_e2e']:.4f} exec={r['timing']['T_exec']:.4f} "
                      + (f"maxerr={rec['metrics']['max_abs_err']:.2e}" if "metrics" in rec else ""), flush=True)
                json.dump(dict(meta=meta, records=recs), open(a.out, "w"))
    d.close()
    meta["end"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    json.dump(dict(meta=meta, records=recs), open(a.out, "w"))


if __name__ == "__main__":
    main()
