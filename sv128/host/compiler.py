"""Host compiler of the complex128 distributed engine: Qiskit circuit -> MUX2 ops -> passes -> segments.

Program = list of steps executed in order by the runtime:
  ("segment", np.int32 stream) : one launch on every engine of every card (all slices)
  ("remap", perm)              : qubit permutation through device swaps or host exchange; perm[new] = old
  ("relabel", table)           : slice relabelling, table[s] = new logical slice index (no data movement)

Gate classes (counted in Stats.route, used by the routing tables of the paper):
  local     : every qubit of the op is local to a slice
  pctrl     : target local, some controls on slice qubits; runs on the engines under a slice enable (F2)
  pdiag     : diagonal op whose target is a slice qubit; scalar phases under slice enables (F1)
  relabel   : X / CX / CCX on slice qubits only, and SWAP; relabelling only (F3, SWAP absorbed always)
  exchange  : any other op touching a slice qubit as target; a remap brings the qubit into the slice first
Flags f1, f2, f3 switch the three slice paths off (they then fall back to exchange) for the ablations.
"""
from dataclasses import dataclass, field
import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Operator
from scipy.linalg import cossin

from isa import MAGIC, OP_MUX2, MAX_OPS_PER_PASS, MAX_HIGH

SKIP = {"measure", "barrier", "delay", "save_statevector", "id"}
I2 = np.eye(2, dtype=complex)
_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Z = np.diag([1, -1]).astype(complex)
MC_GATES = {"ccx": lambda g: _X, "c3x": lambda g: _X, "c4x": lambda g: _X, "mcx": lambda g: _X,
            "mcx_gray": lambda g: _X, "mcx_recursive": lambda g: _X,
            "ccz": lambda g: _Z, "mcphase": lambda g: np.diag([1, np.exp(1j * float(g.params[0]))]),
            "mcp": lambda g: np.diag([1, np.exp(1j * float(g.params[0]))])}
TOL = 1e-12


@dataclass
class Op:
    t: int              # target storage qubit
    ctrls: tuple        # control storage qubits (all must be 1 to select M1)
    M0: np.ndarray
    M1: np.ndarray
    src: object = None

    @property
    def q(self):
        return (self.t,) + tuple(self.ctrls)

    @property
    def diagonal(self):
        return all(abs(M[0, 1]) < TOL and abs(M[1, 0]) < TOL for M in (self.M0, self.M1))


@dataclass
class Stats:
    n_input_gates: int = 0
    native: dict = field(default_factory=dict)
    relabel_swap: int = 0
    lowered: dict = field(default_factory=dict)
    csd_2q: int = 0
    fused_1q: int = 0
    n_ops: int = 0
    n_records: int = 0
    n_passes: int = 0
    n_remaps: int = 0
    n_remaps_slice: int = 0    # remaps that move a slice qubit (data crosses slices)
    n_wide: int = 0            # gates wider than the tile window, made native by placing controls on slice qubits
    n_relabels: int = 0
    n_segments: int = 0
    route: dict = field(default_factory=lambda: {"local": 0, "pctrl": 0, "pdiag": 0, "relabel": 0, "exchange": 0})
    f4_used: bool = False
    n_promote: int = 0         # F4 remaps that move local controls of an X type op up to slice positions


def _bump(d, k):
    d[k] = d.get(k, 0) + 1


def controlled_target(M, nq):
    full = (1 << nq) - 1
    for j in range(nq):
        on = full & ~(1 << j)
        i0, i1 = on, on | (1 << j)
        R = M.copy()
        U = M[np.ix_([i0, i1], [i0, i1])].copy()
        R[np.ix_([i0, i1], [i0, i1])] = I2
        if np.allclose(R, np.eye(1 << nq), atol=TOL):
            return j, U
    return None


def ops_2q(M, a, b, stats):
    """M: 4x4 in basis bit_a + 2 bit_b. 1 op if diagonal or controlled, else 3 via the cosine sine decomposition."""
    if np.allclose(M, np.diag(np.diag(M)), atol=TOL):
        d = np.diag(M)
        return [Op(b, (a,), np.diag([d[0], d[2]]), np.diag([d[1], d[3]]))]
    ct = controlled_target(M, 2)
    if ct is not None:
        j, U = ct
        t, c = (a, b) if j == 0 else (b, a)
        return [Op(t, (c,), I2, U)]
    (u1, u2), th, (v1h, v2h) = cossin(M, p=2, q=2, separate=True)
    c, s_ = np.cos(th), np.sin(th)
    R0 = np.array([[c[0], -s_[0]], [s_[0], c[0]]]); R1 = np.array([[c[1], -s_[1]], [s_[1], c[1]]])
    stats.csd_2q += 1
    return [Op(a, (b,), v1h, v2h), Op(b, (a,), R0, R1), Op(a, (b,), u1, u2)]


def circuit_to_ops(qc: QuantumCircuit, stats: Stats, fuse_1q=True, max_width=None):
    """Returns (ops, relab); SWAPs are absorbed into a relabelling: relab[l] = storage qubit of logical l."""
    n = qc.num_qubits
    relab = list(range(n))
    ops = []
    pending = {}

    def flush(q):
        if q in pending:
            U = pending.pop(q)
            ops.append(Op(q, (), U, U))

    def emit(op_list):
        for op in op_list:
            for q in op.q:
                flush(q)
            ops.append(op)

    def handle(inst, qs, lowered_from=None):
        name = inst.operation.name
        if name in SKIP:
            return
        if lowered_from is None:
            stats.n_input_gates += 1
        if name == "swap":
            a, b = qs
            relab[a], relab[b] = relab[b], relab[a]
            stats.relabel_swap += 1
            return
        st = [relab[q] for q in qs]
        if len(qs) > 2 and name in MC_GATES and (max_width is None or len(qs) <= max_width):
            if lowered_from is None:
                _bump(stats.native, name)
            emit([Op(st[-1], tuple(st[:-1]), I2, MC_GATES[name](inst.operation), src=(inst, qs))])
            return
        if len(qs) > 2 and ((max_width is not None and len(qs) > max_width) or len(qs) > 10):
            if lowered_from is None:
                _bump(stats.native, name)
            lower(inst, qs)
            return
        M = Operator(inst.operation).data
        if lowered_from is None:
            _bump(stats.native, name)
        if len(qs) == 1:
            s = st[0]
            if fuse_1q and s in pending:
                pending[s] = M @ pending[s]; stats.fused_1q += 1
            elif fuse_1q:
                pending[s] = M
            else:
                ops.append(Op(s, (), M, M))
            return
        if len(qs) == 2:
            emit(ops_2q(M, st[0], st[1], stats))
            return
        ct = controlled_target(M, len(qs))
        if ct is not None:
            j, U = ct
            emit([Op(st[j], tuple(x for i, x in enumerate(st) if i != j), I2, U, src=(inst, qs))])
            return
        lower(inst, qs)

    gphase = [float(qc.global_phase)]

    def lower(inst, qs):
        stats.native[inst.operation.name] -= 1
        _bump(stats.lowered, inst.operation.name)
        sub = QuantumCircuit(len(qs))
        sub.append(inst.operation, list(range(len(qs))))
        sub = transpile(sub, basis_gates=["u", "cx"], optimization_level=1)
        gphase[0] += float(sub.global_phase)
        for si in sub.data:
            handle(si, [qs[sub.find_bit(q).index] for q in si.qubits], lowered_from=inst)

    for inst in qc.data:
        handle(inst, [qc.find_bit(q).index for q in inst.qubits])
    if abs(np.exp(1j * gphase[0]) - 1) > TOL:
        ph = np.exp(1j * gphase[0]) * I2
        ops.insert(0, Op(0, (), ph, ph))
    for q in list(pending):
        flush(q)
    stats.n_ops = len(ops)
    return ops, relab


def _pass_m(phys_set, k, M=None):
    """Smallest m in {0 .. M} with |{q >= k-m}| <= m, plus the high qubits; None if infeasible."""
    M = MAX_HIGH if M is None else M
    for m in range(M + 1):
        hi = sorted(q for q in phys_set if q >= k - m)
        if len(hi) <= m:
            return m, hi
    return None


@dataclass
class Rec:
    """One engine record in physical terms."""
    t: int
    cl: tuple           # local control qubits (physical)
    smask: int = 0
    sval: int = 0
    sinv: int = 0
    M0: np.ndarray = None
    M1: np.ndarray = None

    @property
    def local(self):
        return (self.t,) + tuple(self.cl)


def _is_identity(M):
    return np.allclose(M, I2, atol=TOL)


def _is_x(M):
    return np.allclose(M, _X, atol=TOL)


def lower_to_records(op, phys, L, t_free, f1=True, f2=True, f3=True):
    """Returns (kind, payload). kind in {local, pctrl, pdiag, relabel, exchange}; payload = list of Rec,
    or the relabel bit description, or None for exchange."""
    t, ctrl = phys[0], phys[1:]
    cl = tuple(c for c in ctrl if c < L)
    cs = 0
    for c in ctrl:
        if c >= L:
            cs |= 1 << (c - L)
    if t < L:
        if cs == 0:
            return "local", [Rec(t, cl, 0, 0, 0, op.M0, op.M1)]
        if not f2:
            return "exchange", None
        # with no local controls the enabled slices must take M1 for every pair
        recs = [Rec(t, cl, cs, cs, 0, op.M0, op.M1) if cl else Rec(t, (), cs, cs, 0, op.M1, op.M1)]
        if not _is_identity(op.M0):
            recs.append(Rec(t, (), cs, cs, 1, op.M0, op.M0))
        return "pctrl", recs
    tb = 1 << (t - L)
    if f3 and not cl and _is_identity(op.M0) and _is_x(op.M1) or (f3 and not ctrl and _is_x(op.M0)):
        return "relabel", (tb, cs)
    if f1 and op.diagonal:
        recs = []
        for sb in (0, 1):
            a, b = op.M0[sb, sb], op.M1[sb, sb]
            sval = tb if sb else 0
            if abs(a - 1) > TOL:
                recs.append(Rec(t_free, (), tb, sval, 0, a * I2, a * I2))
            r = b / a
            if (cs or cl) and abs(r - 1) > TOL:
                if cl:
                    recs.append(Rec(t_free, cl, tb | cs, sval | cs, 0, I2, r * I2))
                else:
                    recs.append(Rec(t_free, (), tb | cs, sval | cs, 0, r * I2, r * I2))
        return "pdiag", recs
    return "exchange", None


def schedule(ops, n, L, k, stats: Stats, tiling=True, l2p0=None, M=MAX_HIGH, f1=True, f2=True, f3=True, f4=True):
    """Map logical ops to physical passes. Physical qubits >= L are slice qubits."""
    l2p = list(l2p0) if l2p0 is not None else list(range(n))
    steps = []
    cur_passes = []
    cur = []
    cur_set = set()
    k = min(k, L)

    def close_pass():
        nonlocal cur, cur_set
        if cur:
            cur_passes.append(cur)
        cur, cur_set = [], set()

    def close_segment():
        close_pass()
        if cur_passes:
            steps.append(("segment", list(cur_passes)))
            cur_passes.clear()

    def dist(p, idx):
        l = l2p.index(p)
        for j in range(idx, len(ops)):
            if l in ops[j].q:
                return j - idx
        return 10 ** 9

    def do_remap(phys, idx):
        nonlocal l2p
        low = k - M
        assert len(phys) <= low + M, "op wider than the tile window"
        far = lambda p: -dist(p, idx)
        bank = [p for p in phys if p >= L]
        high_local = [p for p in phys if low <= p < L]
        hi_slots = sorted((p for p in range(max(k, L - 6), L) if p not in phys), key=far)
        if bank and len(high_local) + len(bank) <= M and len(hi_slots) >= len(bank):
            move, vic = bank, hi_slots[:len(bank)]
        else:
            keep = high_local[:M]
            move = [p for p in phys if p >= low and p not in keep]
            low_slots = sorted((p for p in range(low) if p not in phys), key=far)
            high_slots = sorted((p for p in range(low, L) if p not in phys), key=far)
            high_free = M - len(keep)
            vic = []
            for _ in move:
                if low_slots:
                    vic.append(low_slots.pop(0))
                elif high_free > 0 and high_slots:
                    vic.append(high_slots.pop(0)); high_free -= 1
                else:
                    raise RuntimeError("cannot fit op into tile window")
        close_segment()
        perm = list(range(n))
        for mq, vq in zip(move, vic):
            perm[mq], perm[vq] = vq, mq
        steps.append(("remap", perm))
        stats.n_remaps += 1
        if bank:
            stats.n_remaps_slice += 1
        inv = {old: new for new, old in enumerate(perm)}
        l2p = [inv[p] for p in l2p]

    def promote(op, phys, idx):
        """F4: X type op (M0 = I, M1 = X) with a slice target and local controls: move the local controls up to slice
        positions (one remap, the same cost as moving the target down); the op and later X type ops among these
        qubits then become slice relabelling (F3) or slice controlled (F2) operations."""
        nonlocal l2p
        cl = [p for p in phys[1:] if p < L]
        far = lambda p: -dist(p, idx)
        vic = sorted((p for p in range(L, n) if p not in phys), key=far)[:len(cl)]
        if len(vic) < len(cl):
            return False
        close_segment()
        perm = list(range(n))
        for c, u in zip(cl, vic):
            perm[c], perm[u] = u, c
        steps.append(("remap", perm))
        stats.n_remaps += 1; stats.n_remaps_slice += 1; stats.n_promote += 1
        inv = {old: new for new, old in enumerate(perm)}
        l2p = [inv[p] for p in l2p]
        return True

    def place_wide(op, phys, idx):
        """Gate with more qubits than the tile window: one remap that brings the target into the slice (swapped with
        one of its own local controls, which then becomes a slice control) and moves surplus local controls to slice
        positions not used by the gate. Afterwards target and local controls fit the window and the gate lowers to
        local or slice controlled (F2) records."""
        nonlocal l2p
        t, ctrls = phys[0], phys[1:]
        far = lambda p: -dist(p, idx)
        swaps = []
        if t >= L:
            lc = sorted((c for c in ctrls if c < L), key=far)
            if lc:
                swaps.append((t, lc[0]))
            else:
                v = sorted((p for p in range(L) if p not in phys), key=far)[0]
                swaps.append((t, v))
        moved = {b for _, b in swaps}
        local_after = [p for p in phys if p < L and p not in moved] + [b for _, b in swaps]
        excess = len(local_after) - k
        if excess > 0:
            target_pos = swaps[0][1] if swaps else t
            cand = sorted((c for c in local_after if c != target_pos), key=far)[:excess]
            free = sorted((p for p in range(L, n) if p not in phys), key=far)
            if len(free) < len(cand):
                raise RuntimeError("gate wider than the tile window plus the free slice qubits")
            swaps += list(zip(cand, free))
        if not swaps:
            return phys
        close_segment()
        perm = list(range(n))
        for a_, b_ in swaps:
            perm[a_], perm[b_] = b_, a_
        steps.append(("remap", perm))
        stats.n_remaps += 1; stats.n_remaps_slice += 1; stats.n_wide += 1
        inv = {old: new for new, old in enumerate(perm)}
        l2p = [inv[p] for p in l2p]
        return [l2p[q] for q in op.q]

    def pick_free(phys):
        busy = set(p for p in phys if p < L)
        cand = sorted(q for q in cur_set if q not in busy) or [q for q in range(L) if q not in busy]
        # only the partition diagonal path (slice target) uses the free qubit; a gate that fills every local qubit
        # always has a local target after place_wide and never takes that path
        return cand[0] if cand else None

    for idx, op in enumerate(ops):
        phys = [l2p[q] for q in op.q]
        if len(phys) > k and (phys[0] >= L or sum(1 for p in phys if p < L) > k):
            phys = place_wide(op, phys, idx)
        t_free = pick_free(phys)
        kind, payload = lower_to_records(op, phys, L, t_free, f1, f2, f3)
        if kind == "exchange":
            if (f4 and f3 and phys[0] >= L and any(p < L for p in phys[1:]) and _is_identity(op.M0) and _is_x(op.M1)
                    and promote(op, phys, idx)):
                phys = [l2p[q] for q in op.q]
                kind, payload = lower_to_records(op, phys, L, pick_free(phys), f1, f2, f3)
                assert kind == "relabel", kind
            else:
                do_remap(phys, idx)
                phys = [l2p[q] for q in op.q]
                kind, payload = lower_to_records(op, phys, L, pick_free(phys), f1, f2, f3)
                assert kind in ("local", "pctrl"), kind
            stats.route["exchange"] += 1
        else:
            stats.route[kind] += 1
        if kind == "relabel":
            tb, cs = payload
            close_segment()
            S = 1 << (n - L)
            steps.append(("relabel", [s ^ tb if (s & cs) == cs else s for s in range(S)]))
            stats.n_relabels += 1
            continue
        for rec in payload:
            loc = set(rec.local)
            if _pass_m(loc, k, M) is None:
                do_remap(list(rec.local), idx)
                # recompute this op from scratch after the local remap
                return_phys = [l2p[q] for q in op.q]
                kind2, payload2 = lower_to_records(op, return_phys, L, pick_free(return_phys), f1, f2, f3)
                assert kind2 != "exchange"
                payload[:] = []
                pending = payload2
                break
        else:
            pending = payload
        for rec in pending:
            loc = set(rec.local)
            new_set = cur_set | loc
            if (not tiling and cur) or len(cur) >= MAX_OPS_PER_PASS or _pass_m(new_set, k, M) is None:
                close_pass()
                new_set = loc
            cur.append(rec)
            cur_set = new_set
            stats.n_records += 1
    close_segment()
    return steps, l2p


def _words_f64(Mat):
    f = np.asarray(Mat, dtype=np.complex128).reshape(-1)
    d = np.empty(8, dtype=np.float64)
    d[0::2] = f.real
    d[1::2] = f.imag
    return list(d.view(np.int32))


def encode_segment(passes, L, k, M=MAX_HIGH):
    words = [MAGIC, L, len(passes), k, 0, 0, 0, 0]
    for p in passes:
        phys_set = set(q for r in p for q in r.local)
        m, hi = _pass_m(phys_set, k, M)
        h = hi + [0] * (4 - len(hi))
        tmap = {q: q for q in phys_set if q < k - m}
        for i, q in enumerate(hi):
            tmap[q] = k - m + i
        words += [m, h[0], h[1], len(p), h[2], h[3], 0, 0]
        for r in p:
            cmask = 0
            for c in r.cl:
                cmask |= 1 << tmap[c]
            words += [OP_MUX2, tmap[r.t], cmask, r.smask, r.sval, r.sinv, 0, 0] + _words_f64(r.M0) + _words_f64(r.M1)
    arr = np.asarray(words, dtype=np.int64)
    return (arr & 0xFFFFFFFF).astype(np.uint32).view(np.int32)


def compile_circuit(qc, L, k, fuse_1q=True, tiling=True, initial_map=None, max_high=MAX_HIGH,
                    f1=True, f2=True, f3=True, f4="auto"):
    """Full pipeline. f4: True, False or "auto" (schedule both ways, keep the one with fewer remaps; ties keep F4 off)."""
    if f4 == "auto":
        a = compile_circuit(qc, L, k, fuse_1q, tiling, initial_map, max_high, f1, f2, f3, False)
        if not (f3 and any(op for op in qc.data if op.operation.name in ("cx", "ccx", "mcx", "x"))):
            return a
        b = compile_circuit(qc, L, k, fuse_1q, tiling, initial_map, max_high, f1, f2, f3, True)
        best = b if b[2].n_remaps < a[2].n_remaps else a
        best[2].f4_used = best is b
        return best
    """Single schedule. L = local qubits per slice; slices = 2^(n-L) (cards x engines per card)."""
    k = min(k, L)
    max_high = max(0, min(max_high, k - 3))
    stats = Stats()
    n = qc.num_qubits
    # a multi controlled gate stays one record if its target and local controls fit the tile window and the rest of
    # its controls sit on slice qubits (slice enable, F2); without F2 it is decomposed as before
    ops, relab = circuit_to_ops(qc, stats, fuse_1q, max_width=k + (n - L) if f2 else k)
    steps, l2p_end = schedule(ops, n, L, k, stats, tiling, initial_map, max_high, f1, f2, f3, f4)
    prog = []
    if initial_map is not None and list(initial_map) != list(range(n)):
        perm = [0] * n
        for l, p in enumerate(initial_map):
            perm[p] = l
        prog.append(("remap", perm))
    for kind, payload in steps:
        if kind == "segment":
            prog.append(("segment", encode_segment(payload, L, k, max_high)))
            stats.n_segments += 1
            stats.n_passes += len(payload)
        else:
            prog.append((kind, payload))
    final_map = [l2p_end[relab[l]] for l in range(n)]
    return prog, final_map, stats
