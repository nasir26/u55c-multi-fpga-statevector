#!/usr/bin/env python3
"""E12 microbenchmarks of the submitted design (v06 or v07 kernel, one card worker per process).

Author: Nasir Ali, C-DAC Noida.

  launch       : v06 kernel launch with zero gates (upload of an empty gate buffer, start, wait)
  gate1(nlq)   : one single qubit gate (H on qubit 0) per launch, nlq = 4 .. nmax
  sync(nlq)    : collect (8 bank read and de interleave) and distribute (interleave and 8 bank write) of a slice
  queue_rtt    : coordinator to worker command round trip with an empty command, all cards
  barrier      : one multiprocessing.Barrier wait across all card processes
usage: micro_baseline.py <xclbin> <cards> <nmax> <out.json>
"""
import json, os, sys, time
import multiprocessing as mp
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions


def card_proc(card, bdf, xclbin, nmax, reps, bar, cmdq, resq):
    import uuid  # noqa: F401
    import pyxrt
    import fpga_simulator_v06 as v06
    eng = v06.QuantumFPGACircuit.__new__(v06.QuantumFPGACircuit)
    eng.xclbin_path, eng.device_index = xclbin, card
    eng.device = pyxrt.device(bdf); eng.xclbin_uuid = eng.device.load_xclbin(xclbin)
    eng.kernel = pyxrt.kernel(eng.device, eng.xclbin_uuid, v06.KERNEL_NAME)
    eng.hbm_banks = [None] * v06.NUM_HBM_BANKS; eng._current_bank_bytes = 0; eng._gate_bo = None; eng._gate_bo_size = 0
    eng._sv_buffer = None; eng._sv_buffer_n = 0; eng._index_cache = {}; eng._debug = False
    out = dict(launch={}, gate1={}, collect={}, distribute={})
    if card == 0:
        for nlq in range(4, nmax + 1):
            eng._distribute_statevector(nlq)
            t = []
            for _ in range(reps):
                a = time.perf_counter(); eng._upload_gate_buffer(np.zeros(8, np.int32)); eng._launch_kernel(0, nlq)
                t.append(time.perf_counter() - a)
            out["launch"][nlq] = t
            t = []
            for _ in range(reps):
                a = time.perf_counter(); eng._execute_segment([("h", [0], None)], nlq); t.append(time.perf_counter() - a)
            out["gate1"][nlq] = t
            sv = np.zeros(1 << nlq, np.complex128); sv[0] = 1
            tc, td = [], []
            for _ in range(reps):
                a = time.perf_counter(); eng._collect_statevector(nlq); tc.append(time.perf_counter() - a)
                a = time.perf_counter(); eng._distribute_arbitrary_state(sv, nlq); td.append(time.perf_counter() - a)
            out["collect"][nlq] = tc; out["distribute"][nlq] = td
    resq.put(("ready", card))
    while True:
        cmd = cmdq.get()
        if cmd == "stop":
            break
        if cmd == "ping":
            resq.put(("pong", card))
        elif cmd == "barrier":
            a = time.perf_counter(); bar.wait(); resq.put(("bar", card, time.perf_counter() - a))
    resq.put(("result", card, out))


def main():
    xclbin, C, nmax, dst = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    reps = 11
    ctx = mp.get_context("spawn")
    bar = ctx.Barrier(C); resq = ctx.Queue(); cmdq = [ctx.Queue() for _ in range(C)]
    ps = [ctx.Process(target=card_proc, args=(c, BDF[c], xclbin, nmax, reps, bar, cmdq[c], resq)) for c in range(C)]
    for p in ps:
        p.start()
    for _ in range(C):
        assert resq.get()[0] == "ready"
    rtt, bars = [], []
    for _ in range(200):
        a = time.perf_counter()
        for q in cmdq:
            q.put("ping")
        for _ in range(C):
            resq.get()
        rtt.append(time.perf_counter() - a)
    for _ in range(200):
        a = time.perf_counter()
        for q in cmdq:
            q.put("barrier")
        for _ in range(C):
            resq.get()
        bars.append(time.perf_counter() - a)
    for q in cmdq:
        q.put("stop")
    res = {}
    for _ in range(C):
        m = resq.get()
        res[m[1]] = m[2]
    out = dict(meta=dict(cmd=" ".join(sys.argv), xclbin=xclbin, cards=BDF[:C], time=time.strftime("%Y-%m-%dT%H:%M:%S%z")),
               queue_rtt=rtt, barrier_round=bars, card0=res[0])
    json.dump(out, open(dst, "w"))
    for nlq in sorted(res[0]["gate1"], key=int):
        print(f"nlq={nlq} launch={np.median(res[0]['launch'][nlq]) * 1e6:.0f}us gate1={np.median(res[0]['gate1'][nlq]) * 1e3:.3f}ms "
              f"collect={np.median(res[0]['collect'][nlq]) * 1e3:.3f}ms distribute={np.median(res[0]['distribute'][nlq]) * 1e3:.3f}ms")
    print(f"queue rtt median {np.median(rtt) * 1e6:.0f}us; barrier round median {np.median(bars) * 1e6:.0f}us")


if __name__ == "__main__":
    main()
