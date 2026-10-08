"""Instruction set of the complex128 distributed statevector engine (shared by the host compiler,
the NumPy golden model and the HLS kernel).

All records are 32 bit words; matrices are float64 bit patterns (two words each, low word first).

The global statevector of n qubits is split into S = C * P slices (C cards, P engine pseudo channels per card),
each of 2^L amplitudes. Physical qubits 0 .. L-1 are local to a slice; physical qubits L .. n-1 select the slice
("slice qubits"; the top log2(C) of them select the card).

Stream layout (one kernel launch executes one segment = list of passes between host remaps):
  word 0          : MAGIC
  word 1          : L      (local qubits per slice)
  word 2          : n_passes
  word 3          : k      (tile = 2^k amplitudes)
  words 4 .. 7    : reserved
  then per pass   : PASS_WORDS header + n_ops * OP_WORDS op records

Pass header: [m, h0, h1, n_ops, h2, h3, 0, 0]
  m in {0 .. MAX_HIGH}: number of high local qubits gathered into the tile; tile qubit k-m+i is physical h_i,
  tile qubits 0 .. k-m-1 are physical qubits 0 .. k-m-1.

Op record (OP_WORDS = 40): [OP_MUX2, t, cmask, smask, sval, sinv, 0, 0, w0 .. w31]
  t      : tile qubit the 2x2 acts on
  cmask  : mask over tile qubits; a pair (i0, i1) along t uses M1 if (i0 & cmask) == cmask (cmask != 0), else M0
  smask, sval, sinv : slice enable. The op runs on a slice with logical index s iff
           ((s & smask) == sval) XOR sinv; otherwise the slice is left unchanged.
  w0 .. w15  = M0 (m00 m01 m10 m11 as re, im; float64), w16 .. w31 = M1.

Gate mapping (host): 1q U -> MUX2(t, 0, U, U); controlled U with local controls -> cmask; controls on slice
qubits -> slice enable; diagonal gates whose target is a slice qubit -> scalar phase ops on any local qubit
under a slice enable; X / CX / CCX acting only on slice qubits -> relabelling of slices (no data movement);
any other gate whose target is a slice qubit -> remap (exchange) first.
"""
MAGIC = 0x51535633  # "QSV3"
HDR_WORDS = 8
PASS_WORDS = 8
OP_WORDS = 40
OP_MUX2 = 1
MAX_OPS_PER_PASS = 64
MAX_HIGH = 4      # default; must not exceed the kernel build's MAXH
AMP_BYTES = 16
