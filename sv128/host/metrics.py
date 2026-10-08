"""State comparison metrics used for every reported instance (prompt Sec 5, fidelity reporting).

F = |<ref|psi>|^2 / (<ref|ref><psi|psi>)
one_minus_F: computed from the phase aligned residual, 1 - F = d^2 - d^4/4 with d = || psi - e^{i phi} ref ||
             (both normalised, phi the optimal global phase), which avoids the cancellation of 1 - F near 1;
             for d < 1e-6 this equals d^2 to working precision.
max_abs_err, l2_err: phase aligned amplitude errors; raw_max_abs_err without phase alignment.
"""
import numpy as np


def compare(psi, ref):
    psi = np.asarray(psi, dtype=np.complex128); ref = np.asarray(ref, dtype=np.complex128)
    npsi, nref = np.linalg.norm(psi), np.linalg.norm(ref)
    a, b = psi / npsi, ref / nref
    ov = np.vdot(b, a)
    phase = ov / abs(ov) if abs(ov) > 0 else 1.0
    r = a - phase * b
    d = float(np.linalg.norm(r))
    return dict(F=float(abs(ov) ** 2), one_minus_F=d * d - d ** 4 / 4, max_abs_err=float(np.max(np.abs(r))),
                l2_err=d, raw_max_abs_err=float(np.max(np.abs(psi - ref))), norm_err=float(abs(npsi - 1)),
                global_phase=float(np.angle(phase)))
