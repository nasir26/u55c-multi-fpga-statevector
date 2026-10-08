#!/usr/bin/env python3
"""Thermal soak of all cards with the engine bitstream loaded: idle phase, then a sustained load phase.

Author: Nasir Ali, C-DAC Noida.

Reports per card the FPGA and HBM temperature (start, maximum, mean of the last minute) and board power, and the
spread across cards, so that a host can be qualified before timed runs. Stops at the abort limits of
bench/fpga_power.py (FPGA 90 C, HBM 85 C) and always parks the cards on the small bitstream at the end.
usage: thermal_soak.py --xclbin X --park-xclbin V06 [--engines 8 --swaps 4] [--idle-min 10] [--load-min 15] [--n 28] --out R.json
"""
import argparse, json, os, socket, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "sv128", "host")]
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xclbin", required=True)
    ap.add_argument("--park-xclbin", required=True)
    ap.add_argument("--engines", type=int, default=8)
    ap.add_argument("--swaps", type=int, default=4)
    ap.add_argument("--idle-min", type=float, default=10)
    ap.add_argument("--load-min", type=float, default=15)
    ap.add_argument("--n", type=int, default=28)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import fpga_power
    import uuid  # noqa: F401  (pyxrt needs it imported first)
    import pyxrt
    flag = a.out + ".abort"
    if os.path.exists(flag):
        os.remove(flag)
    s = fpga_power.Sampler(BDF, a.out + ".power.csv", abort_flag=flag)
    s.start()
    phases, rt = {}, None

    def snap():
        return {b: (fpga_power._r(fpga_power.xmc_dir(b), "xmc_fpga_temp"), fpga_power._r(fpga_power.xmc_dir(b), "xmc_hbm_temp"))
                for b in BDF}

    def watch(name, minutes, work=None):
        t0 = time.perf_counter(); start = snap(); mx = dict(start); last = []
        runs = 0
        while time.perf_counter() - t0 < minutes * 60:
            if os.path.exists(flag):
                raise SystemExit(f"abort limit reached in phase {name}: {snap()}")
            if work:
                work(); runs += 1
            else:
                time.sleep(2)
            t = snap()
            mx = {b: (max(mx[b][0], t[b][0]), max(mx[b][1], t[b][1])) for b in BDF}
            last.append((time.perf_counter(), t))
            last = [x for x in last if x[0] > time.perf_counter() - 60]
        t1 = time.perf_counter()
        mean_last = {b: (sum(x[1][b][0] for x in last) / len(last), sum(x[1][b][1] for x in last) / len(last)) for b in BDF}
        phases[name] = dict(minutes=minutes, start=start, max=mx, mean_last_minute=mean_last, runs=runs,
                            power_w={b: s.mean_power(b, t0, t1) for b in BDF},
                            spread_fpga_c=max(v[0] for v in mean_last.values()) - min(v[0] for v in mean_last.values()))
        print(name, json.dumps(phases[name]), flush=True)

    try:
        from runtime import DistSVRuntime
        import circuits as C
        rt = DistSVRuntime(BDF, a.xclbin, a.engines, a.swaps)
        watch("idle_engine_loaded", a.idle_min)
        qc = C.qft(a.n)
        watch(f"load_qft{a.n}_{len(BDF)}cards", a.load_min, work=lambda: rt.run(qc, return_state=False))
    finally:
        s.stop()
        rt = None
        import gc; gc.collect()          # release the engine buffers and device handles before parking
        for b in BDF:
            try:
                pyxrt.device(b).load_xclbin(a.park_xclbin)
            except Exception as ex:  # noqa: BLE001
                print("park failed", b, ex)
        json.dump(dict(host=socket.gethostname(), bdfs=BDF, xclbin=os.path.abspath(a.xclbin), cmd=" ".join(sys.argv),
                       time=time.strftime("%Y-%m-%dT%H:%M:%S%z"), phases=phases), open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
