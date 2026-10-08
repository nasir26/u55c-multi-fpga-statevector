// ============================================================
// quantum_fpga_kernel_complex128_v06.cpp
// Version  : v06
// Precision: complex128 (double, 2 × float64 per amplitude)
// Target   : Xilinx Alveo U55C — xilinx_u55c_gen3x16_xdma_3_202210_1
// Kernel   : quantum_fpga_kernel_complex128
// Author   : Nasir Ali — C-DAC Noida
//
// ROUTING FIX — 8 HBM banks  (down from 16)
// ------------------------------------------
// v06 attempt 2 failed with:
//   "Routing results verification failed due to partially-conflicted nets"
//   in bank0_m_axi_U/bus_read/rreq_burst_conv/rs_req
//
// Root cause: 16 independent AXI4 master ports (one per HBM bank)
// + 1 gate port = 17 AXI masters inside one kernel shell.
// The AXI burst-conversion FIFOs for bank0 ended up in a routing
// island after 4 global rip-up/reroute iterations.
//
// Fix: reduce HBM banks from 16 → 8.
//   AXI master count: 17 → 9  (8 amplitude banks + 1 gate port)
//   Bank interleaving: i % 8  (was i % 16)
//   Each bank now holds 2× more amplitudes than before.
//   gate_sequence mapped to HBM[8].
//
// Kernel still has only 3 compute functions (SQ_LOOP / CX_LOOP / CZ_LOOP).
// All other gates decomposed on the Python host before the gate buffer
// is sent to the FPGA.
//
// Kernel opcode table (19 opcodes):
//   0  ID      no-op
//   1  H       Hadamard
//   2  X       Pauli-X
//   3  Y       Pauli-Y
//   4  Z       Pauli-Z
//   5  S       S gate
//   6  T       T gate
//   7  SDG     S†
//   8  TDG     T†
//   9  SX      √X
//  10  SXDG    (√X)†
//  11  RX      RX(θ)
//  12  RY      RY(θ)
//  13  RZ      RZ(θ)
//  14  P       Phase(θ) / U1
//  15  U2      U2(φ,λ)
//  16  U3      U3(θ,φ,λ) / U
//  17  CX      CNOT
//  18  CZ      controlled-Z
//
// Gate buffer: 8 × int32 per gate
//   word 0: opcode
//   word 1: qubit0
//   word 2: qubit1  (-1 if unused)
//   word 3: qubit2  (-1 if unused)
//   word 4: param0 as float32 bits in int32
//   word 5: param1 as float32 bits in int32
//   word 6: param2 as float32 bits in int32
//   word 7: padding / reserved
// ============================================================

#include <ap_int.h>
#include <hls_math.h>

// ── Opcode constants ─────────────────────────────────────────
#define GATE_ID    0
#define GATE_H     1
#define GATE_X     2
#define GATE_Y     3
#define GATE_Z     4
#define GATE_S     5
#define GATE_T     6
#define GATE_SDG   7
#define GATE_TDG   8
#define GATE_SX    9
#define GATE_SXDG  10
#define GATE_RX    11
#define GATE_RY    12
#define GATE_RZ    13
#define GATE_P     14
#define GATE_U2    15
#define GATE_U3    16
#define GATE_CX    17
#define GATE_CZ    18

// ── Bank count ───────────────────────────────────────────────
#define NUM_BANKS  8
#define BANK_MASK  0x7     // i % 8
#define BANK_SHIFT 3       // i >> 3  gives slot

// ── Bank pointer macros ──────────────────────────────────────
#define BANK_PARAMS \
    double* b0, double* b1, double* b2, double* b3, \
    double* b4, double* b5, double* b6, double* b7

#define BANK_ARGS \
    b0, b1, b2, b3, b4, b5, b6, b7

#define BANK_ARGS_K \
    bank0, bank1, bank2, bank3, bank4, bank5, bank6, bank7

// ── Amplitude I/O ─────────────────────────────────────────────
// Global index i → bank = i & 0x7,  slot = i >> 3
// Each slot stores [re, im] as two consecutive doubles.
inline void read_amp(int idx, double &re, double &im, BANK_PARAMS) {
    #pragma HLS INLINE
    int bank = idx & BANK_MASK;
    int off  = (idx >> BANK_SHIFT) << 1;
    double *p;
    switch (bank) {
        case 0: p = b0; break; case 1: p = b1; break;
        case 2: p = b2; break; case 3: p = b3; break;
        case 4: p = b4; break; case 5: p = b5; break;
        case 6: p = b6; break; default: p = b7; break;
    }
    re = p[off]; im = p[off + 1];
}

inline void write_amp(int idx, double re, double im, BANK_PARAMS) {
    #pragma HLS INLINE
    int bank = idx & BANK_MASK;
    int off  = (idx >> BANK_SHIFT) << 1;
    double *p;
    switch (bank) {
        case 0: p = b0; break; case 1: p = b1; break;
        case 2: p = b2; break; case 3: p = b3; break;
        case 4: p = b4; break; case 5: p = b5; break;
        case 6: p = b6; break; default: p = b7; break;
    }
    p[off] = re; p[off + 1] = im;
}

// ── Complex multiply ─────────────────────────────────────────
inline void cmul(double ar, double ai, double br, double bi,
                 double &rr, double &ri) {
    #pragma HLS INLINE
    rr = ar * br - ai * bi;
    ri = ar * bi + ai * br;
}

// ============================================================
//  FUNCTION 1 — apply_single_gate
//  One function, one shared FP64 datapath — all 17 single-qubit
//  opcodes call it with different matrix coefficients.
// ============================================================
static void apply_single_gate(
    BANK_PARAMS,
    int tgt, int nq,
    double g00r, double g00i,
    double g01r, double g01i,
    double g10r, double g10i,
    double g11r, double g11i
) {
    const int pairs  = 1 << (nq - 1);
    const int stride = 1 << tgt;

    SQ_LOOP: for (int p = 0; p < pairs; p++) {
        #pragma HLS PIPELINE II=16
        #pragma HLS LOOP_TRIPCOUNT min=1 max=268435456

        int i0 = ((p >> tgt) << (tgt + 1)) | (p & (stride - 1));
        int i1 = i0 + stride;

        double a0r, a0i, a1r, a1i;
        read_amp(i0, a0r, a0i, BANK_ARGS);
        read_amp(i1, a1r, a1i, BANK_ARGS);

        double t0r, t0i, t1r, t1i;
        cmul(g00r, g00i, a0r, a0i, t0r, t0i);
        cmul(g01r, g01i, a1r, a1i, t1r, t1i);
        double n0r = t0r + t1r, n0i = t0i + t1i;

        cmul(g10r, g10i, a0r, a0i, t0r, t0i);
        cmul(g11r, g11i, a1r, a1i, t1r, t1i);
        double n1r = t0r + t1r, n1i = t0i + t1i;

        write_amp(i0, n0r, n0i, BANK_ARGS);
        write_amp(i1, n1r, n1i, BANK_ARGS);
    }
}

// ============================================================
//  FUNCTION 2 — apply_cnot
// ============================================================
static void apply_cnot(BANK_PARAMS, int ctrl, int tgt, int nq) {
    const int N      = 1 << nq;
    const int c_mask = 1 << ctrl;
    const int t_mask = 1 << tgt;

    CX_LOOP: for (int i = 0; i < N; i++) {
        #pragma HLS PIPELINE II=16
        #pragma HLS LOOP_TRIPCOUNT min=2 max=536870912

        if ((i & c_mask) && (i < (i ^ t_mask))) {
            int j = i ^ t_mask;
            double ar, ai, br, bi;
            read_amp(i, ar, ai, BANK_ARGS);
            read_amp(j, br, bi, BANK_ARGS);
            write_amp(i, br, bi, BANK_ARGS);
            write_amp(j, ar, ai, BANK_ARGS);
        }
    }
}

// ============================================================
//  FUNCTION 3 — apply_cz
// ============================================================
static void apply_cz(BANK_PARAMS, int ctrl, int tgt, int nq) {
    const int N      = 1 << nq;
    const int c_mask = 1 << ctrl;
    const int t_mask = 1 << tgt;

    CZ_LOOP: for (int i = 0; i < N; i++) {
        #pragma HLS PIPELINE II=8
        #pragma HLS LOOP_TRIPCOUNT min=2 max=536870912

        if ((i & c_mask) && (i & t_mask)) {
            double re, im;
            read_amp(i, re, im, BANK_ARGS);
            write_amp(i, -re, -im, BANK_ARGS);
        }
    }
}

// ============================================================
//  TOP-LEVEL KERNEL
// ============================================================
extern "C" void quantum_fpga_kernel_complex128(
    double* bank0, double* bank1, double* bank2, double* bank3,
    double* bank4, double* bank5, double* bank6, double* bank7,
    int*    gate_sequence,
    int     num_gates,
    int     num_qubits
) {
    #pragma HLS INTERFACE m_axi port=bank0 offset=slave bundle=bank0
    #pragma HLS INTERFACE m_axi port=bank1 offset=slave bundle=bank1
    #pragma HLS INTERFACE m_axi port=bank2 offset=slave bundle=bank2
    #pragma HLS INTERFACE m_axi port=bank3 offset=slave bundle=bank3
    #pragma HLS INTERFACE m_axi port=bank4 offset=slave bundle=bank4
    #pragma HLS INTERFACE m_axi port=bank5 offset=slave bundle=bank5
    #pragma HLS INTERFACE m_axi port=bank6 offset=slave bundle=bank6
    #pragma HLS INTERFACE m_axi port=bank7 offset=slave bundle=bank7
    #pragma HLS INTERFACE m_axi port=gate_sequence offset=slave bundle=gmem0

    #pragma HLS INTERFACE s_axilite port=bank0         bundle=control
    #pragma HLS INTERFACE s_axilite port=bank1         bundle=control
    #pragma HLS INTERFACE s_axilite port=bank2         bundle=control
    #pragma HLS INTERFACE s_axilite port=bank3         bundle=control
    #pragma HLS INTERFACE s_axilite port=bank4         bundle=control
    #pragma HLS INTERFACE s_axilite port=bank5         bundle=control
    #pragma HLS INTERFACE s_axilite port=bank6         bundle=control
    #pragma HLS INTERFACE s_axilite port=bank7         bundle=control
    #pragma HLS INTERFACE s_axilite port=gate_sequence bundle=control
    #pragma HLS INTERFACE s_axilite port=num_gates     bundle=control
    #pragma HLS INTERFACE s_axilite port=num_qubits    bundle=control
    #pragma HLS INTERFACE s_axilite port=return        bundle=control

    // ── Load gate sequence into BRAM ──────────────────────────
    int gbuf[512 * 8];
    #pragma HLS BIND_STORAGE variable=gbuf type=ram_2p impl=bram

    int total = num_gates * 8;
    LOAD: for (int i = 0; i < total; i++) {
        #pragma HLS PIPELINE II=1
        #pragma HLS LOOP_TRIPCOUNT min=8 max=4096
        gbuf[i] = gate_sequence[i];
    }

    // ── Execute gates ─────────────────────────────────────────
    EXEC: for (int g = 0; g < num_gates; g++) {
        #pragma HLS LOOP_TRIPCOUNT min=1 max=512

        int base = g * 8;
        int op   = gbuf[base];
        int q0   = gbuf[base + 1];
        int q1   = gbuf[base + 2];

        // Parameters packed as float32 bits in int32 words.
        union { int i; float f; } p0, p1, p2;
        p0.i = gbuf[base + 4];
        p1.i = gbuf[base + 5];
        p2.i = gbuf[base + 6];
        double dp0 = (double)p0.f;
        double dp1 = (double)p1.f;
        double dp2 = (double)p2.f;

        if (op == GATE_ID) {
            /* no-op */

        } else if (op == GATE_H) {
            const double h = 0.7071067811865476;
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                 h, 0.0,  h, 0.0,
                 h, 0.0, -h, 0.0);

        } else if (op == GATE_X) {
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                0.0, 0.0, 1.0, 0.0,
                1.0, 0.0, 0.0, 0.0);

        } else if (op == GATE_Y) {
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                0.0,  0.0, 0.0, -1.0,
                0.0,  1.0, 0.0,  0.0);

        } else if (op == GATE_Z) {
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                1.0, 0.0,  0.0, 0.0,
                0.0, 0.0, -1.0, 0.0);

        } else if (op == GATE_S) {
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                1.0, 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 1.0);

        } else if (op == GATE_T) {
            const double t = 0.7071067811865476;
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                1.0, 0.0, 0.0, 0.0,
                0.0, 0.0,   t,   t);

        } else if (op == GATE_SDG) {
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                1.0, 0.0, 0.0,  0.0,
                0.0, 0.0, 0.0, -1.0);

        } else if (op == GATE_TDG) {
            const double t = 0.7071067811865476;
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                1.0, 0.0, 0.0, 0.0,
                0.0, 0.0,   t,  -t);

        } else if (op == GATE_SX) {
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                0.5,  0.5,  0.5, -0.5,
                0.5, -0.5,  0.5,  0.5);

        } else if (op == GATE_SXDG) {
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                0.5, -0.5,  0.5,  0.5,
                0.5,  0.5,  0.5, -0.5);

        } else if (op == GATE_RX) {
            double c = hls::cos(dp0 * 0.5);
            double s = hls::sin(dp0 * 0.5);
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                  c, 0.0, 0.0,  -s,
                0.0,  -s,   c, 0.0);

        } else if (op == GATE_RY) {
            double c = hls::cos(dp0 * 0.5);
            double s = hls::sin(dp0 * 0.5);
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                c, 0.0, -s, 0.0,
                s, 0.0,  c, 0.0);

        } else if (op == GATE_RZ) {
            double c = hls::cos(dp0 * 0.5);
            double s = hls::sin(dp0 * 0.5);
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                c, -s, 0.0, 0.0,
                0.0, 0.0, c,  s);

        } else if (op == GATE_P) {
            double c = hls::cos(dp0);
            double s = hls::sin(dp0);
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                1.0, 0.0, 0.0, 0.0,
                0.0, 0.0,   c,   s);

        } else if (op == GATE_U2) {
            const double inv_sqrt2 = 0.7071067811865476;
            double cphi = hls::cos(dp0), sphi = hls::sin(dp0);
            double clam = hls::cos(dp1), slam = hls::sin(dp1);
            double cpl  = hls::cos(dp0 + dp1);
            double spl  = hls::sin(dp0 + dp1);
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                 inv_sqrt2,              0.0,
                -inv_sqrt2 * clam, -inv_sqrt2 * slam,
                 inv_sqrt2 * cphi,  inv_sqrt2 * sphi,
                 inv_sqrt2 * cpl,   inv_sqrt2 * spl);

        } else if (op == GATE_U3) {
            double ct   = hls::cos(dp0 * 0.5), st = hls::sin(dp0 * 0.5);
            double cphi = hls::cos(dp1),       sphi = hls::sin(dp1);
            double clam = hls::cos(dp2),       slam = hls::sin(dp2);
            double cpl  = hls::cos(dp1 + dp2);
            double spl  = hls::sin(dp1 + dp2);
            apply_single_gate(BANK_ARGS_K, q0, num_qubits,
                  ct,          0.0,
                -st * clam,  -st * slam,
                 st * cphi,   st * sphi,
                 ct * cpl,    ct * spl);

        } else if (op == GATE_CX) {
            apply_cnot(BANK_ARGS_K, q0, q1, num_qubits);

        } else if (op == GATE_CZ) {
            apply_cz(BANK_ARGS_K, q0, q1, num_qubits);
        }
    }
}