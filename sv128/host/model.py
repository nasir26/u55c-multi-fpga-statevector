"""NumPy golden model of the complex128 engine: executes an encoded segment exactly as the engines do,
slice by slice and tile by tile, in complex128 arithmetic. Validates the compiler against Qiskit and the
HLS C simulation against the model."""
import numpy as np
from isa import MAGIC, HDR_WORDS, PASS_WORDS, OP_WORDS, OP_MUX2


def decode(seg):
    seg = np.asarray(seg, dtype=np.int32)
    assert seg[0] == MAGIC
    L, npass, k = int(seg[1]), int(seg[2]), int(seg[3])
    pos = HDR_WORDS
    passes = []
    for _ in range(npass):
        m, h0, h1, nops, h2, h3 = (int(x) for x in seg[pos:pos + 6]); pos += PASS_WORDS
        ops = []
        for _ in range(nops):
            rec = seg[pos:pos + OP_WORDS]; pos += OP_WORDS
            f = np.ascontiguousarray(rec[8:40]).view(np.float64)
            c = f[0::2] + 1j * f[1::2]
            hdr = [int(x) & 0xFFFFFFFF for x in rec[:6]]
            ops.append((hdr[0], hdr[1], hdr[2], hdr[3], hdr[4], hdr[5],
                        c[:4].reshape(2, 2), c[4:].reshape(2, 2)))
        passes.append((m, [h0, h1, h2, h3][:m], ops))
    return L, k, passes


def tile_index_map(L, k, m, hi):
    """idx[t, j]: local slice index of tile element j in tile t (shape 2^(L-k) x 2^k)."""
    hi = list(hi)[:m]
    low = k - m
    used = set(range(low)) | set(hi)
    free = [b for b in range(L) if b not in used]
    assert len(free) == L - k
    j = np.arange(1 << k, dtype=np.int64)
    off = j & ((1 << low) - 1)
    for i, h in enumerate(hi):
        off |= ((j >> (low + i)) & 1) << h
    t = np.arange(1 << (L - k), dtype=np.int64)
    base = np.zeros_like(t)
    for i, b in enumerate(free):
        base |= ((t >> i) & 1) << b
    return base[:, None] | off[None, :]


def enabled(s, smask, sval, sinv):
    return ((s & smask) == sval) != bool(sinv)


def apply_op_tile(T, t, cmask, M0, M1):
    nt, size = T.shape
    k = size.bit_length() - 1
    V = T.reshape(nt, 1 << (k - t - 1), 2, 1 << t)
    i0 = np.arange(size).reshape(1 << (k - t - 1), 2, 1 << t)[:, 0, :]
    sel = ((i0 & cmask) == cmask) if cmask else np.zeros_like(i0, dtype=bool)
    x0, x1 = V[:, :, 0, :].copy(), V[:, :, 1, :].copy()
    for M, mask in ((M0, ~sel), (M1, sel)):
        y0 = M[0, 0] * x0 + M[0, 1] * x1
        y1 = M[1, 0] * x0 + M[1, 1] * x1
        V[:, :, 0, :] = np.where(mask[None], y0, V[:, :, 0, :])
        V[:, :, 1, :] = np.where(mask[None], y1, V[:, :, 1, :])


def run_segment(state, S, seg, slice_ids=None):
    """state: global complex128 vector stored as S physical slices of 2^L; slice_ids[p] = logical slice index
    held in physical slot p (identity if None)."""
    L, k, passes = decode(seg)
    assert state.size == S << L
    sid = list(range(S)) if slice_ids is None else slice_ids
    for m, hi, ops in passes:
        idx = tile_index_map(L, k, m, hi)
        for p in range(S):
            sl = state[p << L:(p + 1) << L]
            T = sl[idx]
            for code, t, cm, smask, sval, sinv, M0, M1 in ops:
                assert code == OP_MUX2
                if enabled(sid[p], smask, sval, sinv):
                    apply_op_tile(T, t, cm, M0, M1)
            sl[idx] = T
    return state


def remap(state, n, perm):
    """perm[new_phys] = old_phys: new bit position new_phys takes the old bit old_phys."""
    v = state.reshape([2] * n)          # axis i corresponds to bit n-1-i
    axes = [n - 1 - perm[n - 1 - i] for i in range(n)]
    return np.ascontiguousarray(np.transpose(v, axes)).reshape(-1)


def unpermute(state, n, final_map):
    """final_map[l] = physical position of logical qubit l: return the state in logical order."""
    return remap(state, n, [final_map[l] for l in range(n)])


def gather_slices(state, L, slice_ids):
    """Physical slot order -> logical slice order."""
    S = len(slice_ids)
    out = np.empty_like(state)
    for p, s in enumerate(slice_ids):
        out[s << L:(s + 1) << L] = state[p << L:(p + 1) << L]
    return out


def run_program(prog, n, L, final_map, state=None):
    """Executes a compiled program on the full vector, tracking which logical slice sits in each slot
    (slice relabelling steps move no data)."""
    S = 1 << (n - L)
    if state is None:
        state = np.zeros(1 << n, dtype=np.complex128); state[0] = 1
    state = np.array(state, dtype=np.complex128)
    sid = list(range(S))
    for kind, payload in prog:
        if kind == "segment":
            run_segment(state, S, payload, sid)
        elif kind == "relabel":
            # payload[s] = new logical index of the slice that had logical index s
            sid = [payload[s] for s in sid]
        else:
            state = gather_slices(state, L, sid); sid = list(range(S))
            state = remap(state, n, payload)
    state = gather_slices(state, L, sid)
    return unpermute(state, n, final_map)
