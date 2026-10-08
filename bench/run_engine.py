#!/usr/bin/env python3
"""Experiment driver for the complex128 distributed engine (E1 to E7, E10, E14).

Author: Nasir Ali, C-DAC Noida.

Every record: circuit, n, cards, engines, flags, repetition, all timing fields of DistSVRuntime, routing and
exchange counters, and (outside the timed region) the error metrics against an independent reference:
Qiskit Statevector for n <= REF_SV_MAX, Qiskit Aer statevector (double precision, fusion off) above.
Repetition 0 is a warm up and is flagged; the analysis excludes it.
usage example:
  run_engine.py --xclbin X --cards 4 --engines 16 --swaps 4 --circuits qft,ghz --ns 20,24,28 --reps 6 --out R.json
"""
import argparse, hashlib, json, os, platform, socket, subprocess, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "sv128", "host")]
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions
DEFAULT_CARDS = {1: os.environ.get("QSIM_CARDS1", "0000:41:00.1").split(","),           # coolest cards of the original host
                 2: os.environ.get("QSIM_CARDS2", "0000:41:00.1,0000:a1:00.1").split(","), 4: BDF}
REF_SV_MAX = 20
PRE_FPGA_C, PRE_HBM_C = 87, 82   # pre run guard: park and cool before a repetition if a card is this hot


def build(name, n):
    import circuits as C
    if name == "qft":
        return C.qft(n)
    if name.startswith("qftb"):
        return C.qft_basis(n, int(name[4:], 2) if set(name[4:]) <= {"0", "1"} else int(name[4:]))
    if name == "qft_iqft":
        return C.qft_roundtrip(n)
    if name == "ghz":
        return C.ghz_chain(n)
    if name == "ghz_top":
        return C.ghz_rooted_top(n)
    if name == "ghz_log":
        return C.ghz_logdepth(n)
    if name == "bell":
        return C.bell(n)
    if name == "grover":
        return C.grover_kopt(n)
    if name.startswith("rand"):
        return C.random_circuit(n, int(name[4:] or 10))
    if name == "partition_heavy":
        return C.partition_heavy(n)
    if name == "shor15":
        return C.shor_qpe_7_mod_15(n - 4)
    if name == "qpe":
        return C.phase_qpe(n - 1, 0.3125)
    raise ValueError(name)


def reference(qc, init):
    n = qc.num_qubits
    if n <= REF_SV_MAX:
        from qiskit.quantum_info import Statevector
        sv = Statevector(init) if init is not None else Statevector.from_int(0, 2 ** n)
        return sv.evolve(qc).data, "qiskit.Statevector"
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    sim = AerSimulator(method="statevector", precision="double", fusion_enable=False)
    q2 = qc.copy()
    if init is not None:
        from qiskit import QuantumCircuit
        q3 = QuantumCircuit(n); q3.initialize(init, range(n)); q3.compose(qc, inplace=True); q2 = q3
    q2.save_statevector()
    t = transpile(q2, sim, optimization_level=0)
    return np.asarray(sim.run(t).result().get_statevector()), "qiskit_aer.AerSimulator(double, fusion off)"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xclbin", required=True)
    ap.add_argument("--cards", type=int, default=4)
    ap.add_argument("--bdfs", default=None, help="comma separated, default the first <cards> of " + ",".join(BDF))
    ap.add_argument("--engines", type=int, default=16)
    ap.add_argument("--swaps", type=int, default=4)
    ap.add_argument("--circuits", required=True)
    ap.add_argument("--ns", required=True)
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--flags", default="111a", help="f1 f2 f3 f4 (1, 0; f4 also a = auto), comma separated list allowed")
    ap.add_argument("--init", default="zero", choices=["zero", "haar"])
    ap.add_argument("--no-device-swap", action="store_true")
    ap.add_argument("--ref-max", type=int, default=30, help="largest n with a reference comparison")
    ap.add_argument("--part", default="", help="logical qubits placed at the top (partition) positions, e.g. 0,1; default: the top qubits")
    ap.add_argument("--cool-c", type=float, default=80.0, help="wait until every card is below this FPGA temperature")
    ap.add_argument("--park-xclbin", default=os.path.join(HERE, "..", "..", "builds", "v06", "quantum_fpga_kernel_complex128_v06.xclbin"),
                    help="small bitstream loaded on the cards while they cool (the engine bitstream heats idle cards)")
    ap.add_argument("--power", action="store_true", help="sample board power and temperature of every card")
    ap.add_argument("--pin-cores", type=int, default=0, help="restrict the host process (and its threads and workers) to cores 0 .. N-1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mock", action="store_true", help="development only: mocked XRT, output must not enter results/")
    a = ap.parse_args()
    if a.pin_cores:
        os.sched_setaffinity(0, set(range(a.pin_cores)))
    if a.mock:
        assert "/results/" not in os.path.abspath(a.out), "mock output must not be written to results/"
        sys.path.insert(0, os.path.join(HERE, "..", "sv128", "tests"))
        import mock_pyxrt; mock_pyxrt.install()
    from runtime import DistSVRuntime
    import circuits as Cm
    from metrics import compare
    bdfs = a.bdfs.split(",") if a.bdfs else DEFAULT_CARDS[a.cards]
    rt = None
    git = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    meta = dict(mock=a.mock, cmd=" ".join(sys.argv), start=time.strftime("%Y-%m-%dT%H:%M:%S%z"), host=socket.gethostname(),
                python=platform.python_version(), git=git, xclbin=os.path.abspath(a.xclbin), xclbin_sha256=sha(a.xclbin) if os.path.exists(a.xclbin) else None,
                bdfs=bdfs, engines=a.engines, swaps=a.swaps, init=a.init, seed=Cm.SEED, pin_cores=a.pin_cores, park_xclbin=os.path.abspath(a.park_xclbin))
    recs, stops = [], []
    sampler = None
    if not a.mock:
        import fpga_power
        abort_flag = a.out + ".abort"
        # the sampler always runs: it records temperatures and sets the abort flag at 90 C FPGA or 85 C HBM
        sampler = fpga_power.Sampler(bdfs, a.out + ".power.csv", abort_flag=abort_flag)
        sampler.start()

    def temps():
        out = {}
        for b in bdfs:
            d = fpga_power.xmc_dir(b)
            out[b] = (fpga_power._r(d, "xmc_fpga_temp"), fpga_power._r(d, "xmc_hbm_temp"))
        return out

    def park():
        """Replace the engine bitstream by the small one on every card (the engine bitstream heats idle cards)."""
        nonlocal rt
        if a.mock:
            return
        rt = None
        import gc; gc.collect()
        import pyxrt
        for b in bdfs:
            pyxrt.device(b).load_xclbin(a.park_xclbin)

    def cool():
        """Park, wait until every card is below the start limit, stop at the abort limits. Returns seconds waited."""
        if a.mock:
            return 0.0
        t0 = time.perf_counter()
        park()
        while True:
            t = temps()
            if any(f >= fpga_power.FPGA_LIMIT_C or h >= fpga_power.HBM_LIMIT_C for f, h in t.values()):
                raise SystemExit(f"card at the abort limit while cooling: {t}")
            if all(f < a.cool_c for f, h in t.values()):
                break
            if time.perf_counter() - t0 > 1800:
                raise SystemExit(f"cards did not cool below {a.cool_c} C within 30 min: {t}")
            time.sleep(10)
        return time.perf_counter() - t0
    try:
        for name in a.circuits.split(","):
            for n in [int(x) for x in a.ns.split(",")]:
                qc = build(name, n)
                init = Cm.haar_state(n) if a.init == "haar" else None
                for fl in a.flags.split(","):
                    fl = fl + "a" * (4 - len(fl))
                    f1, f2, f3 = (c == "1" for c in fl[:3])
                    f4 = "auto" if fl[3] == "a" else fl[3] == "1"
                    ref = None
                    imap = None
                    if a.part:
                        top = [int(x) for x in a.part.split(",")]
                        rest = [q for q in range(n) if q not in top]
                        imap = [0] * n                                     # imap[logical] = physical
                        for i, q in enumerate(rest):
                            imap[q] = i
                        for i, q in enumerate(reversed(top)):
                            imap[q] = n - len(top) + i
                    # park and cool only when a card is at or above the start limit; otherwise keep the loaded engine
                    hot = (not a.mock) and any(fv >= a.cool_c for fv, hv in temps().values())
                    cool_s, setup_s = 0.0, 0.0
                    if hot or rt is None:
                        if hot:
                            cool_s = cool()
                        t_s = time.perf_counter()
                        rt = DistSVRuntime(bdfs, a.xclbin, a.engines, a.swaps, use_device_swap=not a.no_device_swap)
                        setup_s = time.perf_counter() - t_s
                    for rep in range(a.reps):
                        # pre run guard: a card close to the limit is parked and cooled before the repetition starts,
                        # so that the abort limit is not crossed during a long run
                        pre_cool = 0.0
                        if not a.mock and any(fv >= PRE_FPGA_C or hv >= PRE_HBM_C for fv, hv in temps().values()):
                            pre_cool = cool()
                            rt = DistSVRuntime(bdfs, a.xclbin, a.engines, a.swaps, use_device_swap=not a.no_device_swap)
                        t_run0 = time.perf_counter()
                        r = rt.run(qc, shots=1024, f1=f1, f2=f2, f3=f3, f4=f4, return_state=(rep == a.reps - 1), seed=rep, initial_map=imap,
                                   init_state=init)
                        rec = dict(circuit=name, n=n, C=rt.C, P=r["P"], L=r["L"], k=r["k"], flags=fl, init=a.init, part=a.part or "top", rep=rep, warmup=rep == 0,
                                   timing=r["timing"], stats={k: v for k, v in r["stats"].items() if k in
                                                              ("route", "n_records", "n_passes", "n_remaps", "n_remaps_slice",
                                                               "n_relabels", "n_segments", "n_input_gates", "fused_1q",
                                                               "f4_used", "n_promote")},
                                   meta_qc=getattr(qc, "metadata", None) or {}, cool_wait_s=cool_s if rep == 0 else 0.0, T_setup=setup_s)
                        rec["pre_cool_s"] = pre_cool
                        thermal = os.path.exists(a.out + ".abort")
                        if thermal:
                            rec["thermal_abort"] = open(a.out + ".abort").read().strip()
                        if sampler and a.power:
                            t_run1 = time.perf_counter()
                            rec["power_w"] = {b: sampler.mean_power(b, t_run0, t_run1) for b in bdfs}
                            rec["power_readings"] = {b: sampler.n_readings(b, t_run0, t_run1) for b in bdfs}
                        if "state" in r and n <= a.ref_max:
                            t0 = time.perf_counter()
                            if ref is None:
                                ref, ref_src = reference(qc, init)
                            rec["metrics"] = compare(r["state"], ref); rec["reference"] = ref_src
                            rec["T_reference"] = time.perf_counter() - t0
                            if name == "grover":
                                rec["P_target"] = float(abs(r["state"][qc.metadata["marked"]]) ** 2)
                            if name.startswith("shor15") or name == "qpe":
                                t = n - 4 if name.startswith("shor15") else n - 1
                                pr = (np.abs(r["state"].reshape(-1, 1 << t)) ** 2).sum(axis=0)
                                prr = (np.abs(ref.reshape(-1, 1 << t)) ** 2).sum(axis=0)
                                rec["counting_dist_max_abs_diff"] = float(np.max(np.abs(pr - prr)))
                                rec["counting_top4"] = [(int(i), float(pr[i])) for i in np.argsort(pr)[::-1][:4]]
                        recs.append(rec)
                        T = r["timing"]
                        print(f"{name:14s} n={n:2d} C={rt.C} P={r['P']} f={fl} rep={rep} e2e={T['T_e2e']:.4f} kern={T['T_kernel']:.4f} "
                              f"exch={T['T_exchange']:.4f} " + (f"maxerr={rec['metrics']['max_abs_err']:.2e} 1-F={rec['metrics']['one_minus_F']:.2e}"
                                                             if "metrics" in rec else ""), flush=True)
                        json.dump(dict(meta=meta, records=recs, thermal_stops=stops), open(a.out, "w"))
                        if thermal:
                            # the run finished but a card crossed the abort limit: stop this instance, record it, cool
                            # down and continue with the next instance
                            stops.append(dict(circuit=name, n=n, C=rt.C, flags=fl, init=a.init, reps_done=rep + 1,
                                              reps_planned=a.reps, abort=rec["thermal_abort"], time=time.strftime("%Y-%m-%dT%H:%M:%S%z")))
                            print(f"THERMAL STOP {name} n={n} flags={fl} after {rep + 1} of {a.reps} repetitions: {rec['thermal_abort']}", flush=True)
                            cool()
                            os.remove(a.out + ".abort")
                            if sampler:
                                sampler.aborted = False
                            rt = DistSVRuntime(bdfs, a.xclbin, a.engines, a.swaps, use_device_swap=not a.no_device_swap)
                            json.dump(dict(meta=meta, records=recs, thermal_stops=stops), open(a.out, "w"))
                            break
                    ref = None if init is None else ref
    finally:
        try:
            park()
        except Exception as e:  # noqa: BLE001
            print("park failed:", e, flush=True)
    if sampler:
        sampler.stop()
    meta["end"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    json.dump(dict(meta=meta, records=recs, thermal_stops=stops), open(a.out, "w"))


if __name__ == "__main__":
    main()
