"""Baseline: the submitted distributed design (three path router, three barrier exchange) on the 8 bank complex128
v06 kernel (or the v07 kernel, same interface), one worker process per card.

Author: Nasir Ali, C-DAC Noida.

Per card execution uses QuantumFPGACircuit from fpga_simulator_v06.py unchanged (state in 8 HBM banks, modulo 8
interleave, 19 opcodes, gate parameters as float32). This file adds the distributed layer described in the
submitted manuscript (Sec 3.4, 5.1 to 5.3), with the routing decided on the circuit gates before lowering:
  local    : every qubit below nlq = n - log2(C): lowered to the 19 native opcodes and executed by the kernel
             on every card (consecutive local gates form one kernel segment, chunked by 512)
  diagonal : diagonal gate touching a partition qubit: slice read from HBM, NumPy phase multiply, written back
  exchange : any other gate touching a partition qubit: three barrier protocol through shared host memory;
             each card publishes its slice (HBM read), computes its own new slice from its partners' slices
             in NumPy, and writes it back to HBM.
Timing per phase is recorded by every worker; PCIe bytes are counted from the HBM transfers.
"""
import uuid  # noqa: F401  before pyxrt
import ctypes, math, os, sys, time
import multiprocessing as mp
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DIAG_NAMES = {"z", "s", "sdg", "t", "tdg", "rz", "p", "u1", "phase", "cz", "cp", "cphase", "crz", "rzz", "id"}
SUPPORTED = ["id", "h", "x", "y", "z", "s", "t", "sdg", "tdg", "sx", "sxdg", "rx", "ry", "rz", "p", "u2", "u3",
             "cx", "cz", "cy", "ch", "swap", "cp", "crx", "cry", "crz", "csx", "dcx", "iswap", "ecr", "rxx", "ryy",
             "rzz", "ccx"]


def circuit_to_gates(qc):
    """Qiskit circuit -> list of (name, qubits, params, matrix) on the submitted gate set. Multi controlled X gates
    are kept whole by the transpiler and expanded with the v06 host's own _decompose_mcx (Qiskit, optimisation
    level 2, Toffoli based), as in the submitted implementation; settings are fixed for every run."""
    from qiskit import transpile
    from qiskit.circuit.library import get_standard_gate_name_mapping
    from qiskit.quantum_info import Operator
    import fpga_simulator_v06 as v06
    std = get_standard_gate_name_mapping()
    t = transpile(qc, basis_gates=SUPPORTED + ["mcx"], optimization_level=0, seed_transpiler=1)
    gates = []

    def add(nm, qs, ps):
        g = std[nm]
        if ps:
            g = type(g)(*ps)
        gates.append((nm, list(qs), list(ps or []), Operator(g).data))
    for inst in t.data:
        nm = inst.operation.name
        if nm in ("barrier", "measure", "delay"):
            continue
        qs = [t.find_bit(q).index for q in inst.qubits]
        ps = [float(p) for p in inst.operation.params]
        if nm == "mcx":
            for snm, sqs, sps in v06._decompose_mcx(qs):
                add(snm, sqs, [float(p) for p in sps] if sps else [])
        else:
            gates.append((nm, qs, ps, Operator(inst.operation).data))
    return gates, float(t.global_phase) + sum(0.0 for _ in ())


def route(name, qs, M, nlq):
    if all(q < nlq for q in qs):
        return "local"
    if name in DIAG_NAMES or np.allclose(M, np.diag(np.diag(M)), atol=1e-14):
        return "diag"
    return "exchange"


def apply_on_own_slice(slices, myv, pbits, qs, M, nlq):
    """slices[v]: partner slice whose partition bits pbits (list of partition bit indices) equal the bits of v.
    Returns the new slice of this card (whose pbits value is myv) for gate M on qubits qs (Qiskit order)."""
    k = len(qs)
    npart = len(pbits)
    # mini global vector: local qubits 0..nlq-1, then the involved partition bits in pbits order
    V = np.concatenate(slices) if npart else slices[0]
    nn = nlq + npart
    pos = {nlq + pb: nlq + i for i, pb in enumerate(pbits)}
    mq = [pos.get(q, q) for q in qs]
    T = V.reshape([2] * nn)                       # axis a <-> qubit nn-1-a
    axes = [nn - 1 - q for q in mq]
    T = np.moveaxis(T, axes, list(range(k)))      # leading axes: gate qubits, qs[0] first
    G = M.reshape([2] * (2 * k))                  # Qiskit: row bits (q_{k-1} .. q_0), then column bits
    G = np.transpose(G, list(range(k - 1, -1, -1)) + list(range(2 * k - 1, k - 1, -1)))  # -> (out q0..q_{k-1}, in q0..)
    out = np.tensordot(G, T, axes=(list(range(k, 2 * k)), list(range(k))))
    out = np.moveaxis(out, list(range(k)), axes).reshape(-1)
    return out[myv << nlq:(myv + 1) << nlq]


def _shm_view(arr, n):
    return np.frombuffer(arr.get_obj(), dtype=np.complex128, count=n)


def worker(card, bdf, xclbin, C, nlq, R, W, bars, cmdq, resq):
    import fpga_simulator_v06 as v06
    import pyxrt
    T = dict(kernel=0.0, d2h=0.0, h2d=0.0, host_compute=0.0, barrier=0.0, queue=0.0)
    B = dict(pcie_d2h=0, pcie_h2d=0)
    try:
        eng = v06.QuantumFPGACircuit.__new__(v06.QuantumFPGACircuit)
        eng.xclbin_path, eng.device_index = xclbin, card
        eng.device = pyxrt.device(bdf)
        eng.xclbin_uuid = eng.device.load_xclbin(xclbin)
        eng.kernel = pyxrt.kernel(eng.device, eng.xclbin_uuid, v06.KERNEL_NAME)
        eng.hbm_banks = [None] * v06.NUM_HBM_BANKS
        eng._current_bank_bytes = 0; eng._gate_bo = None; eng._gate_bo_size = 0
        eng._sv_buffer = None; eng._sv_buffer_n = 0; eng._index_cache = {}; eng._debug = False
        resq.put(("ready", card))
        nbytes = (1 << nlq) * 16
        bA, bB, bC = bars
        while True:
            t_wait = time.perf_counter()
            cmd = cmdq.get()
            T["queue"] += time.perf_counter() - t_wait
            kind = cmd[0]
            if kind == "stop":
                break
            if kind == "init_state":
                a = time.perf_counter()
                eng._distribute_arbitrary_state(_shm_view(R[card], 1 << nlq).copy(), nlq)
                for k_ in T:
                    T[k_] = 0.0
                for k_ in B:
                    B[k_] = 0
                T["h2d"] = time.perf_counter() - a; B["pcie_h2d"] = nbytes
                resq.put(("ok", card))
                continue
            if kind == "init":
                a = time.perf_counter()
                if card == 0:
                    eng._distribute_statevector(nlq)
                else:
                    eng._distribute_arbitrary_state(np.zeros(1 << nlq, np.complex128), nlq)
                T["h2d"] += time.perf_counter() - a; B["pcie_h2d"] += nbytes
                for k_ in T:
                    T[k_] = 0.0
                for k_ in B:
                    B[k_] = 0
                T["h2d"] = time.perf_counter() - a; B["pcie_h2d"] = nbytes
                resq.put(("ok", card))
            elif kind == "local":
                a = time.perf_counter()
                lowered = v06._lower_to_kernel_basis(cmd[1])
                eng._execute_segment(lowered, nlq)
                T["kernel"] += time.perf_counter() - a
                resq.put(("ok", card))
            elif kind == "diag":
                _, M, qs = cmd
                a = time.perf_counter()
                sv = eng._collect_statevector(nlq).copy(); b = time.perf_counter()
                new = apply_on_own_slice([sv], 0, [], [q for q in qs], M, nlq) if all(q < nlq for q in qs) else None
                if new is None:
                    # phase depends on this card's partition bits and possibly on local bits
                    pb = [q - nlq for q in qs if q >= nlq]
                    myv = sum(((card >> p) & 1) << i for i, p in enumerate(pb))
                    d = np.diag(M)
                    idx = np.zeros(1 << nlq, dtype=np.int64)
                    loc = np.arange(1 << nlq, dtype=np.int64)
                    for i, q in enumerate(qs):
                        bit = ((card >> (q - nlq)) & 1) if q >= nlq else ((loc >> q) & 1)
                        idx |= bit << i
                    new = sv * d[idx]
                c = time.perf_counter()
                eng._distribute_arbitrary_state(new, nlq); e = time.perf_counter()
                T["d2h"] += b - a; T["host_compute"] += c - b; T["h2d"] += e - c
                B["pcie_d2h"] += nbytes; B["pcie_h2d"] += nbytes
                resq.put(("ok", card))
            elif kind == "exchange":
                _, M, qs = cmd
                a = time.perf_counter()
                sv = eng._collect_statevector(nlq)
                _shm_view(R[card], 1 << nlq)[:] = sv
                b = time.perf_counter(); bA.wait(); c = time.perf_counter()
                pbits = sorted(set(q - nlq for q in qs if q >= nlq))
                myv = sum(((card >> p) & 1) << i for i, p in enumerate(pbits))
                partners = []
                for v in range(1 << len(pbits)):
                    j = card
                    for i, p in enumerate(pbits):
                        j = (j & ~(1 << p)) | (((v >> i) & 1) << p)
                    partners.append(_shm_view(R[j], 1 << nlq))
                new = apply_on_own_slice(partners, myv, pbits, qs, M, nlq)
                _shm_view(W[card], 1 << nlq)[:] = new
                d = time.perf_counter(); bB.wait(); e = time.perf_counter()
                eng._distribute_arbitrary_state(_shm_view(W[card], 1 << nlq), nlq)
                f = time.perf_counter(); bC.wait(); g = time.perf_counter()
                T["d2h"] += b - a; T["host_compute"] += d - c; T["h2d"] += f - e
                T["barrier"] += (c - b) + (e - d) + (g - f)
                B["pcie_d2h"] += nbytes; B["pcie_h2d"] += nbytes
                resq.put(("ok", card))
            elif kind == "collect":
                a = time.perf_counter()
                sv = eng._collect_statevector(nlq)
                _shm_view(R[card], 1 << nlq)[:] = sv
                T["d2h"] += time.perf_counter() - a; B["pcie_d2h"] += nbytes
                resq.put(("collected", card, dict(T), dict(B)))
    except Exception as ex:  # noqa: BLE001
        import traceback
        resq.put(("error", card, f"{ex}\n{traceback.format_exc()}"))


class DistV06:
    def __init__(self, bdfs, xclbin, max_n=28):
        mp.set_start_method("spawn", force=True)
        self.C = len(bdfs)
        self.npb = self.C.bit_length() - 1
        self.bdfs, self.xclbin, self.max_n = bdfs, xclbin, max_n
        self.procs = None

    def _start(self, nlq):
        if self.procs is not None and self.nlq == nlq:
            return
        self.close()
        self.nlq = nlq
        ctx = mp.get_context("spawn")
        n = 1 << nlq
        self.R = [ctx.Array(ctypes.c_double, 2 * n) for _ in range(self.C)]
        self.W = [ctx.Array(ctypes.c_double, 2 * n) for _ in range(self.C)]
        bars = tuple(ctx.Barrier(self.C) for _ in range(3))
        self.cmdq = [ctx.Queue() for _ in range(self.C)]
        self.resq = ctx.Queue()
        t0 = time.perf_counter()
        self.procs = [ctx.Process(target=worker, args=(c, self.bdfs[c], self.xclbin, self.C, nlq, self.R, self.W, bars,
                                                       self.cmdq[c], self.resq), daemon=True) for c in range(self.C)]
        for p in self.procs:
            p.start()
        self._gather("ready")
        self.T_setup = time.perf_counter() - t0

    def _gather(self, want):
        out = []
        for _ in range(self.C):
            m = self.resq.get(timeout=3600)
            if m[0] == "error":
                raise RuntimeError(f"card {m[1]}: {m[2]}")
            assert m[0] == want, m
            out.append(m)
        return out

    def _bcast(self, cmd, want="ok"):
        for q in self.cmdq:
            q.put(cmd)
        return self._gather(want)

    def close(self):
        if self.procs:
            for q in self.cmdq:
                q.put(("stop",))
            for p in self.procs:
                p.join(timeout=30)
        self.procs = None

    def run(self, qc, batch_local=True, init_state=None, diag_path=True):
        """diag_path=False sends partition diagonal gates through the exchange path (ablation of the diagonal path)."""
        n = qc.num_qubits
        nlq = n - self.npb
        t0 = time.perf_counter()
        gates, gphase = circuit_to_gates(qc)
        t1 = time.perf_counter()
        self._start(nlq)
        counts = dict(local=0, diag=0, exchange=0, launches=0)
        t2 = time.perf_counter()
        if init_state is None:
            self._bcast(("init",))
        else:
            for c in range(self.C):
                _shm_view(self.R[c], 1 << nlq)[:] = init_state[c << nlq:(c + 1) << nlq]
            self._bcast(("init_state",))
        t3 = time.perf_counter()
        pending = []

        def flush():
            if pending:
                self._bcast(("local", list(pending)))
                counts["launches"] += 1
                pending.clear()
        for nm, qs, ps, M in gates:
            r = route(nm, qs, M, nlq)
            if r == "diag" and not diag_path:
                r = "exchange"
            counts[r] += 1
            if r == "local":
                pending.append((nm, qs, ps if ps else None))
                if not batch_local:
                    flush()
                continue
            flush()
            self._bcast((r, M, qs))
        flush()
        t4 = time.perf_counter()
        res = self._bcast(("collect",), "collected")
        t5 = time.perf_counter()
        state = np.concatenate([_shm_view(self.R[c], 1 << nlq).copy() for c in range(self.C)])
        state *= np.exp(1j * gphase)
        per_card = {m[1]: (m[2], m[3]) for m in res}
        T = dict(T_compile=t1 - t0, T_spawn=t2 - t1, T_init=t3 - t2, T_exec=t4 - t3, T_collect=t5 - t4,
                 T_e2e=(t1 - t0) + (t5 - t2))
        return dict(state=state, timing=T, per_card=per_card, routing=counts, n=n, C=self.C, nlq=nlq,
                    T_setup=self.T_setup, batch_local=batch_local, diag_path=diag_path)
