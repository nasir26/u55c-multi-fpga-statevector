// Complex128 distributed statevector engine: one compute unit per HBM pseudo channel, instantiated
// N times per card (nk=sv128_engine:N). Executes one segment of the QSV3 instruction stream
// (sv128/host/isa.py) on one statevector slice.
//
// Author: Nasir Ali, C-DAC Noida.
//
// Data: complex128, 2 amplitudes per 256 bit word (lane l: re = bits [128l, 128l+64), im = bits
// [128l+64, 128l+128)), the NumPy complex128 memory layout.
//
// Per pass: DATAFLOW reader (tile blocks, 2 banks) -> compute (tile blocks) -> writer
//   tile = 2^k amplitudes = 2^(k-1) words; a pass may gather m <= MAXH high local qubits, so the tile is
//   2^m sub blocks of 2^(k-m-1) contiguous words (one long burst each).
//   Tile word w is stored in bank popcount(w) & 1 at address w >> 1. Words whose indices differ in one bit
//   are in different banks, so every iteration reads one word from each bank and writes one word to each
//   bank (II = 1, 2 amplitude pairs per cycle).
//   Op MUX2(t, cmask, M0, M1): a pair (i0, i1 = i0 | 1<<t) uses M1 if cmask != 0 and all cmask bits of i0
//   are set, else M0. Slice enable: the op runs only if ((slice_id & smask) == sval) XOR sinv; disabled
//   ops are dropped when the pass is loaded and a pass without enabled ops is skipped (no HBM traffic).
#include <ap_int.h>
#include <hls_stream.h>
#include <hls_streamofblocks.h>

#define KMAX 11
#define NW (1 << (KMAX - 1))   // words per tile (max)
#define HALF (NW / 2)
#define MAXOPS 64
#define OPW 40
#define PASSW 8
#define HDRW 8

typedef ap_uint<256> w256;
typedef w256 bank_t[HALF];
#ifdef SV_WIDE
typedef ap_uint<512> pw_t;
#define PW 2
#else
typedef w256 pw_t;
#define PW 1
#endif

static inline double d_of(ap_uint<64> u) {
    union { unsigned long long i; double d; } c; c.i = (unsigned long long)u; return c.d;
}
static inline ap_uint<64> u_of(double d) {
    union { unsigned long long i; double d; } c; c.d = d; return (ap_uint<64>)c.i;
}
static inline int parity(int w) {
#pragma HLS INLINE
    ap_uint<KMAX> x = w;
    return x.xor_reduce();
}

#ifndef MAXH
#define MAXH 4
#endif
struct PassCfg {
    int L, k, m, h[4];
};

static inline ap_uint<32> free_mask(const PassCfg &c) {
#pragma HLS INLINE
    ap_uint<32> fm = 0;
    for (int b = 0; b < 32; b++) {
#pragma HLS UNROLL
        bool used = (b < c.k - c.m) || (b >= c.L);
        for (int i = 0; i < MAXH; i++) {
#pragma HLS UNROLL
            used = used || (i < c.m && b == c.h[i]);
        }
        fm[b] = used ? 0 : 1;
    }
    return fm;
}
static inline long sub_off(const PassCfg &c, int s) {
#pragma HLS INLINE
    long o = 0;
    for (int i = 0; i < MAXH; i++) {
#pragma HLS UNROLL
        if (i < c.m && ((s >> i) & 1)) o |= (1L << c.h[i]);
    }
    return o;
}

static void reader(const pw_t *st, PassCfg c, hls::stream_of_blocks<bank_t> &q0,
                   hls::stream_of_blocks<bank_t> &q1) {
    const int ntiles = 1 << (c.L - c.k);
    const int lsb = c.k - c.m - 1;            // log2(256 bit words per sub block)
    const int sbw = (1 << lsb) / PW;
    const int nsub = 1 << c.m;
    const ap_uint<32> fm = free_mask(c);
    ap_uint<32> base = 0;
TILES:
    for (int t = 0; t < ntiles; t++) {
        hls::write_lock<bank_t> b0(q0), b1(q1);
    SUBS:
        for (int s = 0; s < nsub; s++) {
            const long wa = (((long)base | sub_off(c, s)) >> 1) / PW;
        WORDS:
            for (int j = 0; j < sbw; j++) {
#pragma HLS PIPELINE II = 1
#pragma HLS LOOP_TRIPCOUNT min = 128 max = 1024
                const pw_t v = st[wa + j];
#ifdef SV_WIDE
                const int w = (s << lsb) | (2 * j);
                const w256 lo = v.range(255, 0), hi = v.range(511, 256);
                if (parity(w)) { b1[w >> 1] = lo; b0[w >> 1] = hi; }
                else           { b0[w >> 1] = lo; b1[w >> 1] = hi; }
#else
                const int w = (s << lsb) | j;
                if (parity(w)) b1[w >> 1] = v; else b0[w >> 1] = v;
#endif
            }
        }
        base = ((base | ~fm) + 1) & fm;
    }
}

static void writer(pw_t *st, PassCfg c, hls::stream_of_blocks<bank_t> &q0,
                   hls::stream_of_blocks<bank_t> &q1) {
    const int ntiles = 1 << (c.L - c.k);
    const int lsb = c.k - c.m - 1;
    const int sbw = (1 << lsb) / PW;
    const int nsub = 1 << c.m;
    const ap_uint<32> fm = free_mask(c);
    ap_uint<32> base = 0;
TILES:
    for (int t = 0; t < ntiles; t++) {
        hls::read_lock<bank_t> b0(q0), b1(q1);
    SUBS:
        for (int s = 0; s < nsub; s++) {
            const long wa = (((long)base | sub_off(c, s)) >> 1) / PW;
        WORDS:
            for (int j = 0; j < sbw; j++) {
#pragma HLS PIPELINE II = 1
#pragma HLS LOOP_TRIPCOUNT min = 128 max = 1024
#ifdef SV_WIDE
                const int w = (s << lsb) | (2 * j);
                pw_t v;
                if (parity(w)) { v.range(255, 0) = b1[w >> 1]; v.range(511, 256) = b0[w >> 1]; }
                else           { v.range(255, 0) = b0[w >> 1]; v.range(511, 256) = b1[w >> 1]; }
                st[wa + j] = v;
#else
                const int w = (s << lsb) | j;
                st[wa + j] = parity(w) ? b1[w >> 1] : b0[w >> 1];
#endif
            }
        }
        base = ((base | ~fm) + 1) & fm;
    }
}

// one pair update with matrix M (8 doubles: m00 m01 m10 m11 as re, im)
static inline void pair2(double x0r, double x0i, double x1r, double x1i, const double M[8],
                         double &y0r, double &y0i, double &y1r, double &y1i) {
#pragma HLS INLINE
    y0r = M[0] * x0r - M[1] * x0i + M[2] * x1r - M[3] * x1i;
    y0i = M[0] * x0i + M[1] * x0r + M[2] * x1i + M[3] * x1r;
    y1r = M[4] * x0r - M[5] * x0i + M[6] * x1r - M[7] * x1i;
    y1i = M[4] * x0i + M[5] * x0r + M[6] * x1i + M[7] * x1r;
}

static void compute(PassCfg c, int nops, const int opt[MAXOPS], const int opc[MAXOPS],
                    const double opm[MAXOPS][16], hls::stream_of_blocks<bank_t> &i0q,
                    hls::stream_of_blocks<bank_t> &i1q, hls::stream_of_blocks<bank_t> &o0q,
                    hls::stream_of_blocks<bank_t> &o1q) {
    const int ntiles = 1 << (c.L - c.k);
    const int nwh = 1 << (c.k - 2);           // iterations per op = words / 2
    w256 wk0[HALF], wk1[HALF];
#pragma HLS BIND_STORAGE variable = wk0 type = ram_t2p impl = bram
#pragma HLS BIND_STORAGE variable = wk1 type = ram_t2p impl = bram
TILES:
    for (int t = 0; t < ntiles; t++) {
        hls::read_lock<bank_t> in0(i0q), in1(i1q);
        hls::write_lock<bank_t> out0(o0q), out1(o1q);
    OPS:
        for (int o = 0; o < nops; o++) {
            // op o+1 reads words written by op o: the PAIRS pipeline drains between ops
#pragma HLS LOOP_FLATTEN off
            const int tq = opt[o], cm = opc[o];
            double M0[8], M1[8];
#pragma HLS ARRAY_PARTITION variable = M0 complete
#pragma HLS ARRAY_PARTITION variable = M1 complete
            for (int e = 0; e < 8; e++) {
#pragma HLS UNROLL
                M0[e] = opm[o][e]; M1[e] = opm[o][8 + e];
            }
            const bool first = (o == 0);
            const bool last = (o == nops - 1);
            const int sb = tq >= 1 ? tq - 1 : 0;
        PAIRS:
            for (int i = 0; i < nwh; i++) {
#pragma HLS PIPELINE II = 1
#pragma HLS LOOP_TRIPCOUNT min = 512 max = 512
#pragma HLS DEPENDENCE variable = wk0 type = inter false
#pragma HLS DEPENDENCE variable = wk1 type = inter false
                int wa, wb;
                if (tq >= 1) {
                    wa = ((i >> sb) << (sb + 1)) | (i & ((1 << sb) - 1));
                    wb = wa | (1 << sb);
                } else {
                    wa = 2 * i; wb = 2 * i + 1;
                }
                const int pa = parity(wa);
                const int a0 = pa ? (wb >> 1) : (wa >> 1);
                const int a1 = pa ? (wa >> 1) : (wb >> 1);
                const w256 r0 = first ? in0[a0] : wk0[a0];
                const w256 r1 = first ? in1[a1] : wk1[a1];
                const w256 A = pa ? r1 : r0;
                const w256 B = pa ? r0 : r1;
                double aR[2], aI[2], bR[2], bI[2];
                for (int l = 0; l < 2; l++) {
#pragma HLS UNROLL
                    aR[l] = d_of(A.range(128 * l + 63, 128 * l)); aI[l] = d_of(A.range(128 * l + 127, 128 * l + 64));
                    bR[l] = d_of(B.range(128 * l + 63, 128 * l)); bI[l] = d_of(B.range(128 * l + 127, 128 * l + 64));
                }
                // pair p: t >= 1: lane p of A with lane p of B; t = 0: (A0, A1) and (B0, B1)
                const bool m0 = (tq == 0);
                double x0r[2], x0i[2], x1r[2], x1i[2];
                int ix0[2];
                for (int p = 0; p < 2; p++) {
#pragma HLS UNROLL
                    if (!m0) {
                        x0r[p] = aR[p]; x0i[p] = aI[p]; x1r[p] = bR[p]; x1i[p] = bI[p]; ix0[p] = wa * 2 + p;
                    } else {
                        const double *SR = p ? bR : aR, *SI = p ? bI : aI;
                        x0r[p] = SR[0]; x0i[p] = SI[0]; x1r[p] = SR[1]; x1i[p] = SI[1];
                        ix0[p] = (p ? wb : wa) * 2;
                    }
                }
                double y0r[2], y0i[2], y1r[2], y1i[2];
                for (int p = 0; p < 2; p++) {
#pragma HLS UNROLL
                    const bool sel = cm != 0 && ((ix0[p] & cm) == cm);
                    double Ms[8];
                    for (int e = 0; e < 8; e++) {
#pragma HLS UNROLL
                        Ms[e] = sel ? M1[e] : M0[e];
                    }
                    pair2(x0r[p], x0i[p], x1r[p], x1i[p], Ms, y0r[p], y0i[p], y1r[p], y1i[p]);
                }
                w256 NA, NB;
                for (int l = 0; l < 2; l++) {
#pragma HLS UNROLL
                    double ar, ai, br, bi;
                    if (!m0) {
                        ar = y0r[l]; ai = y0i[l]; br = y1r[l]; bi = y1i[l];
                    } else {                 // lane l of A is pair 0, lane l of B is pair 1
                        ar = l ? y1r[0] : y0r[0]; ai = l ? y1i[0] : y0i[0];
                        br = l ? y1r[1] : y0r[1]; bi = l ? y1i[1] : y0i[1];
                    }
                    NA.range(128 * l + 63, 128 * l) = u_of(ar); NA.range(128 * l + 127, 128 * l + 64) = u_of(ai);
                    NB.range(128 * l + 63, 128 * l) = u_of(br); NB.range(128 * l + 127, 128 * l + 64) = u_of(bi);
                }
                const w256 n0 = pa ? NB : NA, n1 = pa ? NA : NB;
                if (last) { out0[a0] = n0; out1[a1] = n1; }
                else      { wk0[a0] = n0;  wk1[a1] = n1; }
            }
        }
    }
}

static void run_pass(pw_t *st, PassCfg c, int nops, const int opt[MAXOPS], const int opc[MAXOPS],
                     const double opm[MAXOPS][16]) {
#pragma HLS DATAFLOW
    hls::stream_of_blocks<bank_t, 2> qi0, qi1, qo0, qo1;
    reader(st, c, qi0, qi1);
    compute(c, nops, opt, opc, opm, qi0, qi1, qo0, qo1);
    writer(st, c, qo0, qo1);
}

static inline unsigned int insw(const pw_t *st, long ins_off, int pos) {
#pragma HLS INLINE
    const int per = 8 * PW;
    const pw_t v = st[ins_off / PW + pos / per];
    const int l = pos % per;
    return (unsigned int)v.range(32 * l + 31, 32 * l);
}

// One AXI port per CU: the instruction segment is stored in the same buffer as the slice, from
// 256 bit word ins_off. slice_id: logical index of the slice held by this buffer for this launch.
extern "C" void sv128_engine(pw_t *st, long ins_off, int slice_id) {
#pragma HLS INTERFACE m_axi port = st bundle = gst offset = slave max_read_burst_length = 32 \
    max_write_burst_length = 32 num_read_outstanding = 8 num_write_outstanding = 8 latency = 64 depth = 1048576
#pragma HLS INTERFACE s_axilite port = return
    const int L = insw(st, ins_off, 1), npass = insw(st, ins_off, 2), k = insw(st, ins_off, 3);
    const unsigned int sid = (unsigned int)slice_id;
    int pos = HDRW;
PASSES:
    for (int p = 0; p < npass; p++) {
        PassCfg c;
        c.L = L; c.k = k; c.m = insw(st, ins_off, pos);
        c.h[0] = insw(st, ins_off, pos + 1); c.h[1] = insw(st, ins_off, pos + 2);
        c.h[2] = insw(st, ins_off, pos + 4); c.h[3] = insw(st, ins_off, pos + 5);
        const int nrec = insw(st, ins_off, pos + 3);
        pos += PASSW;
        int opt[MAXOPS], opc[MAXOPS];
        double opm[MAXOPS][16];
#pragma HLS ARRAY_PARTITION variable = opm dim = 2 complete
        int nops = 0;
    LOADOPS:
        for (int o = 0; o < nrec; o++) {
            const unsigned int smask = insw(st, ins_off, pos + 3), sval = insw(st, ins_off, pos + 4),
                               sinv = insw(st, ins_off, pos + 5);
            const bool en = (((sid & smask) == sval) != (sinv != 0));
            if (en) {
                opt[nops] = insw(st, ins_off, pos + 1);
                opc[nops] = insw(st, ins_off, pos + 2);
                for (int e = 0; e < 16; e++) {
#pragma HLS PIPELINE II = 2
                    ap_uint<64> u;
                    u.range(31, 0) = insw(st, ins_off, pos + 8 + 2 * e);
                    u.range(63, 32) = insw(st, ins_off, pos + 9 + 2 * e);
                    opm[nops][e] = d_of(u);
                }
                nops++;
            }
            pos += OPW;
        }
        if (nops > 0) run_pass(st, c, nops, opt, opc, opm);
    }
}
