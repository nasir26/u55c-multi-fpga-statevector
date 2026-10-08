"""Host runtime of the complex128 distributed statevector engine on C Alveo U55C cards (C = 1, 2 or 4).

Author: Nasir Ali, C-DAC Noida.

The n qubit state is split into S = C * P slices of 2^L amplitudes (P engine buffers per card). Physical qubits
0 .. L-1 are local, L .. L+log2(P)-1 select the buffer inside a card, and the top log2(C) select the card.
slot g = card * P + p holds the slice with logical index sid[g].

Steps of a compiled program:
  segment : the same instruction stream runs on every engine of every card, each with its slice id
            (cards run concurrently; one host thread starts and waits all runs)
  relabel : X / CX on slice qubits and slice to slice transpositions: sid update only (no data movement)
  remap   : transpositions local <-> slice bit: partner slices on one card use that card's sv_swap kernel,
            partners on different cards exchange the moving halves through host memory over PCIe;
            local <-> local transpositions are applied on the host per slice (rare; counted separately)

Timing fields (per circuit, T_setup excluded; every field is wall clock from time.perf_counter):
  T_compile, T_alloc, T_h2d (init and instruction uploads), T_kernel (segments), T_exch_dev (device swaps),
  T_exch_host (host exchanges, with its d2h, copy and h2d parts), T_local_remap, T_d2h (final read back),
  T_post (sampling), T_e2e = sum of all except T_alloc. Bytes over PCIe are counted per class.
"""
import uuid  # noqa: F401  must precede pyxrt device init
import os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pyxrt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compiler import compile_circuit  # noqa: E402
from isa import MAGIC, OP_MUX2, AMP_BYTES  # noqa: E402
from model import remap as host_remap  # noqa: E402

TO = pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_TO_DEVICE
FROM = pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE
KMAX = 11          # kernel tile limit (sv128_engine.cpp)
LMIN = 11          # minimum local qubits per slice (padding below)
PC_BYTES = 512 << 20
INS_CAP = 4 << 20
WORD_SWAP = 64


def transpositions(perm):
    p = list(perm)
    out = []
    for i in range(len(p)):
        while p[i] != i:
            j = p[i]
            out.append((min(i, j), max(i, j)))
            p[i], p[j] = p[j], p[i]
    return out


def sample_slices(slices, shots, fmap, n, seed=None, chunk_bits=12):
    """Born rule sampling from slices given in logical slice order; returns {logical index: count}."""
    if shots <= 0:
        return {}
    rng = np.random.default_rng(seed)
    L = slices[0].size.bit_length() - 1
    cb = min(chunk_bits, L)

    def chunk_sums(s):
        f = s.view(np.float64).reshape(-1, 2 << cb)
        return np.einsum("ij,ij->i", f, f)
    with ThreadPoolExecutor(max_workers=min(16, len(slices))) as ex:
        sums = np.concatenate(list(ex.map(chunk_sums, slices)))
    cs = np.cumsum(sums)
    u = rng.random(shots) * cs[-1]
    ch = np.searchsorted(cs, u, side="right").clip(0, sums.size - 1)
    rem = u - np.where(ch > 0, cs[ch - 1], 0.0)
    phys = np.empty(shots, dtype=np.int64)
    per_slice = (1 << L) >> cb
    for c in np.unique(ch):
        sel = np.nonzero(ch == c)[0]
        s = slices[c // per_slice]
        off = (c % per_slice) << cb
        p = np.cumsum(np.abs(s[off:off + (1 << cb)]) ** 2)
        phys[sel] = (c << cb) + np.searchsorted(p, rem[sel], side="right").clip(0, (1 << cb) - 1)
    logical = np.zeros(shots, dtype=np.int64)
    for l in range(n):
        logical |= ((phys >> fmap[l]) & 1) << l
    vals, cnt = np.unique(logical, return_counts=True)
    return {int(v): int(c) for v, c in zip(vals, cnt)}


class Card:
    def __init__(self, bdf, xclbin, n_engines, n_swap):
        self.bdf = bdf
        self.dev = pyxrt.device(bdf)
        self.uuid = self.dev.load_xclbin(xclbin)
        self.eng = [pyxrt.kernel(self.dev, self.uuid, f"sv128_engine:{{sv128_engine_{i + 1}}}") for i in range(n_engines)]
        self.swp = [pyxrt.kernel(self.dev, self.uuid, f"sv_swap:{{sv_swap_{i + 1}}}") for i in range(n_swap)]
        self.pcs = self._read_pcs(xclbin, n_engines)

    @staticmethod
    def _read_pcs(xclbin, n):
        cfg = os.path.join(os.path.dirname(os.path.abspath(xclbin)), "link.cfg")
        pcs = [(None, 1)] * n
        if os.path.exists(cfg):
            for line in open(cfg):
                m = re.match(r"sp=sv128_engine_(\d+)\.st:HBM\[(\d+)(?::(\d+))?\]", line.strip())
                if m and int(m.group(1)) <= n:
                    a = int(m.group(2)); b = int(m.group(3)) if m.group(3) else a
                    pcs[int(m.group(1)) - 1] = (a, b - a + 1)
        return pcs


class DistSVRuntime:
    def __init__(self, bdfs, xclbin, n_engines, n_swap=0, use_device_swap=True, max_high=None, threads=8):
        mf = os.path.join(os.path.dirname(os.path.abspath(xclbin)), "maxh.txt")
        build_maxh = int(open(mf).read()) if os.path.exists(mf) else 4
        if max_high is not None and max_high > build_maxh:
            raise ValueError(f"max_high={max_high} exceeds the build's MAXH={build_maxh}")
        self.max_high = build_maxh if max_high is None else max_high
        C = len(bdfs)
        assert C >= 1 and C & (C - 1) == 0, "number of cards must be a power of two"
        t0 = time.perf_counter()
        self.cards = [Card(b, xclbin, n_engines, n_swap) for b in bdfs]
        self.T_setup = time.perf_counter() - t0
        self.C = C
        self.ne = n_engines
        self.use_device_swap = use_device_swap and n_swap > 0
        self.pool = ThreadPoolExecutor(max_workers=threads)
        self.P = self.L = None
        self.bos = []

    # ---------------------------------------------------------------- planning and allocation
    @property
    def slots_per_card(self):
        return sum(npcs for _, npcs in self.cards[0].pcs)

    def plan(self, n, p_max=None):
        """P buffers per card: one per engine (P = engines) when a slice fits one pseudo channel, else virtual
        slices (several single channel buffers per engine). Small n is padded to LMIN local qubits."""
        cb = self.C.bit_length() - 1
        cap = p_max or self.slots_per_card
        P = min(self.ne, cap)
        while P > 1 and n - cb - (P.bit_length() - 1) < LMIN:
            P //= 2
        def fits(P):
            L = n - cb - (P.bit_length() - 1)
            return (1 << L) * AMP_BYTES + INS_CAP <= PC_BYTES
        while not fits(P) and P * 2 <= cap:
            P *= 2
        if not fits(P):
            raise ValueError(f"n={n} does not fit {self.C} card(s)")
        sb = cb + P.bit_length() - 1
        n_run = max(n, LMIN + sb)
        return P, n_run, n_run - sb

    def _alloc(self, P, L):
        if self.P == P and self.L == L:
            return
        self.bos = []
        import gc; gc.collect()
        nbytes = (1 << L) * AMP_BYTES + INS_CAP
        bos, eng_of = [], []
        for card in self.cards:
            for p in range(P):
                e, j = p % self.ne, p // self.ne
                first, npcs = card.pcs[e]
                if first is not None and nbytes <= PC_BYTES:
                    bank = first + j
                else:
                    assert j == 0, "virtual slices need an explicit single channel binding"
                    bank = card.eng[e].group_id(0)
                bos.append(pyxrt.bo(card.dev, nbytes, pyxrt.bo.flags.normal, bank))
                eng_of.append(e)
        self.bos, self.eng_of = bos, eng_of
        self.P, self.L = P, L
        for g in range(len(bos)):
            self._view(g)[:] = 0
        self.pool_map(lambda g: self.bos[g].sync(TO, (1 << L) * AMP_BYTES, 0), range(len(bos)))
        self.swap_ok = [self.use_device_swap and P >= 2 and self._swap_selftest(c) for c in range(self.C)]

    def pool_map(self, f, it):
        return list(self.pool.map(f, it))

    def _swap_selftest(self, c):
        card = self.cards[c]
        if not card.swp:
            return False
        a, b = self.bos[c * self.P], self.bos[c * self.P + 1]
        va = np.frombuffer(a.map(), dtype=np.uint8, count=128); vb = np.frombuffer(b.map(), dtype=np.uint8, count=128)
        va[:] = 0xA5; vb[:] = 0x5A
        a.sync(TO, 128, 0); b.sync(TO, 128, 0)
        card.swp[0](a, b, 0, 0, 2).wait()
        a.sync(FROM, 128, 0); b.sync(FROM, 128, 0)
        ok = bool((va == 0x5A).all() and (vb == 0xA5).all())
        va[:] = 0; vb[:] = 0
        a.sync(TO, 128, 0); b.sync(TO, 128, 0)
        return ok

    def _view(self, g):
        return np.frombuffer(self.bos[g].map(), dtype=np.complex128, count=1 << self.L)

    def card_of(self, g):
        return g // self.P

    # ---------------------------------------------------------------- steps
    def _upload_ins(self, seg):
        nb = seg.nbytes
        if nb > INS_CAP:
            raise RuntimeError(f"segment of {nb} B exceeds the instruction region")
        off = (1 << self.L) * AMP_BYTES

        def up(g):
            np.frombuffer(self.bos[g].map(), dtype=np.int32, count=seg.size, offset=off)[:] = seg
            self.bos[g].sync(TO, nb, off)
        self.pool_map(up, range(len(self.bos)))
        return nb * len(self.bos)

    def _run_segment(self):
        ins_off = (1 << self.L) * AMP_BYTES // 32
        runs = [self.cards[self.card_of(g)].eng[self.eng_of[g]](self.bos[g], ins_off, int(self.sid[g]))
                for g in range(len(self.bos))]
        for r in runs:
            r.wait()

    def _zero_segment(self):
        L = self.L; k = min(KMAX, L)
        w = [MAGIC, L, 1, k, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0] + [OP_MUX2, 0, 0, 0, 0, 0, 0, 0] + [0] * 32
        return np.asarray(w, dtype=np.int64).astype(np.int32)

    def _init_zero_state(self):
        self._upload_ins(self._zero_segment())
        self._run_segment()
        g0 = self.slot_of(0)
        v = self._view(g0)
        v[:2] = 0; v[0] = 1
        self.bos[g0].sync(TO, 32, 0)

    def slot_of(self, s):
        return self.sid.index(s)

    def _relabel(self, table):
        self.sid = [table[s] for s in self.sid]

    def _swap_slice_bits(self, i, j):
        def sw(s):
            bi, bj = (s >> i) & 1, (s >> j) & 1
            return s ^ ((1 << i) | (1 << j)) if bi != bj else s
        self.sid = [sw(s) for s in self.sid]

    def _exchange(self, j, v, T):
        """Transposition of slice bit j with local bit v: the half of slice s with bit v = 1 swaps with the half
        of slice s | 1<<j with bit v = 0."""
        L = self.L
        cw = (1 << v) * AMP_BYTES
        nchunk = 1 << (L - v - 1)
        pairs = [(self.slot_of(s), self.slot_of(s | (1 << j))) for s in range(len(self.sid)) if not (s >> j) & 1]
        dev_pairs = [(a, b) for a, b in pairs if self.card_of(a) == self.card_of(b) and self.swap_ok[self.card_of(a)]
                     and cw % WORD_SWAP == 0 and nchunk <= 16]     # many tiny chunks: one host transfer is cheaper
        host_pairs = [pr for pr in pairs if pr not in dev_pairs]
        t0 = time.perf_counter()
        if dev_pairs:
            runs, q = [], [0] * self.C
            for a, b in dev_pairs:
                c = self.card_of(a); card = self.cards[c]
                for ch in range(nchunk):
                    offa = ((2 * ch + 1) * cw) // WORD_SWAP
                    offb = (2 * ch * cw) // WORD_SWAP
                    runs.append(card.swp[q[c] % len(card.swp)](self.bos[a], self.bos[b], offa, offb, cw // WORD_SWAP))
                    q[c] += 1
            for r in runs:
                r.wait()
            T["T_exch_dev"] += time.perf_counter() - t0
            T["bytes_exch_dev"] += 2 * len(dev_pairs) * nchunk * cw
            T["n_exch_dev"] += 1
        if host_pairs:
            t1 = time.perf_counter()

            # small chunks (low local qubit): one whole slice transfer per buffer instead of 2^(L-v-1) small ones
            whole = nchunk > 8
            sbytes = (1 << L) * AMP_BYTES

            def d2h(pr):
                a, b = pr
                if whole:
                    self.bos[a].sync(FROM, sbytes, 0); self.bos[b].sync(FROM, sbytes, 0)
                    return
                for ch in range(nchunk):
                    self.bos[a].sync(FROM, cw, (2 * ch + 1) * cw)
                    self.bos[b].sync(FROM, cw, 2 * ch * cw)

            def h2d(pr):
                a, b = pr
                if whole:
                    self.bos[a].sync(TO, sbytes, 0); self.bos[b].sync(TO, sbytes, 0)
                    return
                for ch in range(nchunk):
                    self.bos[a].sync(TO, cw, (2 * ch + 1) * cw)
                    self.bos[b].sync(TO, cw, 2 * ch * cw)

            def copy(pr):
                a, b = pr
                va = self._view(a).reshape(nchunk, 2, 1 << v); vb = self._view(b).reshape(nchunk, 2, 1 << v)
                tmp = va[:, 1, :].copy(); va[:, 1, :] = vb[:, 0, :]; vb[:, 0, :] = tmp
            self.pool_map(d2h, host_pairs); t2 = time.perf_counter()
            self.pool_map(copy, host_pairs); t3 = time.perf_counter()
            self.pool_map(h2d, host_pairs); t4 = time.perf_counter()
            T["T_exch_host"] += t4 - t1
            T["T_exch_host_d2h"] += t2 - t1; T["T_exch_host_copy"] += t3 - t2; T["T_exch_host_h2d"] += t4 - t3
            nbytes = 2 * len(host_pairs) * (sbytes if whole else nchunk * cw)
            T["bytes_pcie_exch"] += 2 * nbytes
            T["n_exch_host"] += 1
            T["n_exch_cross_card"] += sum(self.card_of(a) != self.card_of(b) for a, b in host_pairs)

    def _local_local(self, a, b, T):
        L = self.L
        t0 = time.perf_counter()

        def one(g):
            self.bos[g].sync(FROM, (1 << L) * AMP_BYTES, 0)
            vv = self._view(g)
            perm = list(range(L)); perm[a], perm[b] = b, a
            vv[:] = host_remap(vv.copy(), L, perm)
            self.bos[g].sync(TO, (1 << L) * AMP_BYTES, 0)
        self.pool_map(one, range(len(self.bos)))
        T["T_local_remap"] += time.perf_counter() - t0
        T["bytes_pcie_local_remap"] += 2 * len(self.bos) * (1 << L) * AMP_BYTES

    def _remap(self, perm, T):
        L = self.L
        for a, b in transpositions(perm):
            if b < L:
                self._local_local(a, b, T)
            elif a < L:
                self._exchange(b - L, a, T)
            else:
                self._swap_slice_bits(a - L, b - L)
                T["n_slice_slice_relabel"] += 1

    # ---------------------------------------------------------------- public
    def run(self, qc, shots=1024, k=KMAX, p_max=None, fuse=True, tiling=True, initial_map=None,
            return_state=True, seed=None, f1=True, f2=True, f3=True, trace=False, init_state=None, f4="auto"):
        from qiskit import QuantumCircuit
        n = qc.num_qubits
        P, n_run, L = self.plan(n, p_max)
        k = min(k, L)
        t0 = time.perf_counter()
        if n_run != n:
            q2 = QuantumCircuit(n_run)
            q2.compose(qc.remove_final_measurements(inplace=False), range(n), inplace=True)
            q2.global_phase = qc.global_phase
            qrun = q2
        else:
            qrun = qc.remove_final_measurements(inplace=False)
        prog, fmap, stats = compile_circuit(qrun, L, k, fuse_1q=fuse, tiling=tiling, initial_map=initial_map,
                                            max_high=self.max_high, f1=f1, f2=f2, f3=f3, f4=f4)
        t1 = time.perf_counter()
        self._alloc(P, L)
        self.sid = list(range(len(self.bos)))
        t1b = time.perf_counter()
        if init_state is None:
            self._init_zero_state()
        else:
            # arbitrary initial state (padded qubits are |0>): slot g holds logical slice g
            init = np.asarray(init_state, dtype=np.complex128)
            Ls = 1 << L

            def put(g):
                v = self._view(g)
                lo = g * Ls
                seg = init[lo:lo + Ls]
                v[:] = 0
                v[:seg.size] = seg
                self.bos[g].sync(TO, Ls * AMP_BYTES, 0)
            self.pool_map(put, range(len(self.bos)))
        t2 = time.perf_counter()
        T = dict(T_compile=t1 - t0, T_alloc=t1b - t1, T_h2d=t2 - t1b, T_kernel=0.0, T_exch_dev=0.0, T_exch_host=0.0,
                 T_exch_host_d2h=0.0, T_exch_host_copy=0.0, T_exch_host_h2d=0.0, T_local_remap=0.0, T_relabel=0.0,
                 bytes_exch_dev=0, bytes_pcie_exch=0, bytes_pcie_local_remap=0, bytes_pcie_ins=0,
                 n_exch_dev=0, n_exch_host=0, n_exch_cross_card=0, n_slice_slice_relabel=0, n_launch=0)
        steps = [] if trace else None
        started = init_state is not None
        for kind, payload in prog:
            a = time.perf_counter()
            if kind == "segment":
                started = True
                T["bytes_pcie_ins"] += self._upload_ins(payload); b = time.perf_counter()
                self._run_segment(); c = time.perf_counter()
                T["T_h2d"] += b - a; T["T_kernel"] += c - b; T["n_launch"] += 1
            elif kind == "relabel":
                self._relabel(payload); T["T_relabel"] += time.perf_counter() - a
            else:
                if not started:
                    continue          # |0...0> is invariant under qubit permutations
                self._remap(payload, T)
            if trace:
                steps.append((kind, time.perf_counter() - a))
        a = time.perf_counter()
        self.pool_map(lambda g: self.bos[g].sync(FROM, (1 << L) * AMP_BYTES, 0), range(len(self.bos)))
        b = time.perf_counter()
        T["T_d2h"] = b - a
        logical = [self._view(self.slot_of(s)) for s in range(len(self.bos))]
        counts = sample_slices(logical, shots, fmap, n, seed)
        c = time.perf_counter()
        T["T_post"] = c - b
        T["T_exchange"] = T["T_exch_dev"] + T["T_exch_host"] + T["T_local_remap"] + T["T_relabel"]
        T["T_e2e"] = T["T_compile"] + T["T_h2d"] + T["T_kernel"] + T["T_exchange"] + T["T_d2h"] + T["T_post"]
        out = dict(timing=T, C=self.C, P=P, L=L, k=k, n_run=n_run, stats=dict(stats.__dict__), counts=counts)
        if trace:
            out["steps"] = steps
        if return_state:
            full = np.concatenate(logical)
            out["state"] = host_remap(full, n_run, [fmap[l] for l in range(n_run)])[: 1 << n]
            T["T_state_reorder"] = time.perf_counter() - c
        return out
