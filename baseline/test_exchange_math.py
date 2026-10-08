"""Exchange path arithmetic of dist_v06 (each card computes only its own slice) against Qiskit, no hardware."""
import itertools, sys
import numpy as np
from qiskit.quantum_info import Statevector, random_unitary, random_statevector
from dist_v06 import apply_on_own_slice
rng = np.random.default_rng(1)
worst = 0.0
for n, C in ((6, 2), (7, 4), (9, 4)):
    npb = C.bit_length() - 1; nlq = n - npb
    for k in (1, 2, 3):
        for _ in range(20):
            qs = [int(x) for x in rng.choice(n, k, replace=False)]
            if all(q < nlq for q in qs):
                qs[0] = int(rng.integers(nlq, n))
                if len(set(qs)) < k: continue
            U = random_unitary(2 ** k, seed=int(rng.integers(1 << 30))).data
            psi = random_statevector(2 ** n, seed=int(rng.integers(1 << 30)))
            ref = psi.evolve(U, qargs=qs).data
            sl = [psi.data[c << nlq:(c + 1) << nlq] for c in range(C)]
            pbits = sorted(set(q - nlq for q in qs if q >= nlq))
            out = []
            for card in range(C):
                myv = sum(((card >> p) & 1) << i for i, p in enumerate(pbits))
                partners = []
                for v in range(1 << len(pbits)):
                    j = card
                    for i, p in enumerate(pbits):
                        j = (j & ~(1 << p)) | (((v >> i) & 1) << p)
                    partners.append(sl[j])
                out.append(apply_on_own_slice(partners, myv, pbits, qs, U, nlq))
            worst = max(worst, float(np.max(np.abs(np.concatenate(out) - ref))))
print(f"worst max abs error {worst:.2e}")
sys.exit(0 if worst < 1e-12 else 1)
