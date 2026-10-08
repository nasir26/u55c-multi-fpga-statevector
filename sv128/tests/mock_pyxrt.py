"""Minimal pyxrt stand in for testing the host orchestration without hardware.

BOs are NumPy byte buffers; sv128_engine compute units execute the segment stored at word offset ins_off of
their BO with the golden model (validated against the HLS C simulation); sv_swap swaps two 64 byte word ranges.
sync() is a no op, so the mock checks orchestration and data placement, not transfer timing.
"""
import sys, types
import numpy as np


class _Dir:
    XCL_BO_SYNC_BO_TO_DEVICE = 0
    XCL_BO_SYNC_BO_FROM_DEVICE = 1


class bo:
    class flags:
        normal = 0

    def __init__(self, dev, size, flags, group):
        self.buf = np.zeros(size, dtype=np.uint8)
        self.group = group
        self.dev = dev

    def map(self):
        return memoryview(self.buf)

    def sync(self, d, size, off):
        pass


class _Run:
    def wait(self, *a):
        return "COMPLETED"


class kernel:
    def __init__(self, dev, uuid, name):
        self.name = name
        self.kind = name.split(":")[0]
        self.dev = dev

    def group_id(self, i):
        return self.name

    def __call__(self, *args):
        if self.kind == "sv128_engine":
            st, ins_off, sid = args
            assert st.dev is self.dev, "BO of another card passed to an engine"
            from model import run_segment
            seg = st.buf[ins_off * 32:].view(np.int32)
            L = int(seg[1])
            sl = st.buf[: (1 << L) * 16].view(np.complex128)
            run_segment(sl, 1, seg, [sid])
        elif self.kind == "sv_swap":
            a, b, offa, offb, nw = args
            assert a.dev is self.dev and b.dev is self.dev, "device swap across cards"
            A = a.buf[offa * 64:(offa + nw) * 64]; B = b.buf[offb * 64:(offb + nw) * 64]
            t = A.copy(); A[:] = B; B[:] = t
        return _Run()


class device:
    def __init__(self, bdf):
        self.bdf = bdf

    def load_xclbin(self, path):
        return "uuid"


def install():
    m = types.ModuleType("pyxrt")
    m.device, m.kernel, m.bo, m.xclBOSyncDirection = device, kernel, bo, _Dir
    sys.modules["pyxrt"] = m
