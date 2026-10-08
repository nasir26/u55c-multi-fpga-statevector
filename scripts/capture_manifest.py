#!/usr/bin/env python3
"""Hardware and software manifest of the measurement platform (results/hardware_manifest.json).
Read only: sysfs, /proc, lscpu, xbutil, xclbinutil, package versions, git."""
import glob, hashlib, json, os, platform, re, socket, subprocess, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BDF = os.environ.get("QSIM_BDFS", "0000:01:00.1,0000:21:00.1,0000:41:00.1,0000:a1:00.1").split(",")   # card PCIe user functions
XCLBINS = {"v06": "builds/v06/quantum_fpga_kernel_complex128_v06.xclbin", "sv128_e8w": "builds/sv128_e8w/sv.xclbin",
           "v07": "../opt_kernel/opt_kernel/quantum_fpga_kernel_complex128.xclbin"}


def sh(cmd):
    return subprocess.run(cmd, shell=True, executable="/bin/bash", capture_output=True, text=True).stdout.strip()


def rd(p):
    try:
        return open(p).read().strip()
    except OSError:
        return None


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    xrt = "source /opt/xilinx/xrt/setup.sh >/dev/null 2>&1; "
    cards = []
    for b in BDF:
        x = (glob.glob(f"/sys/bus/pci/devices/{b}/xmc.u.*") or [None])[0]
        ex = sh(xrt + f"xbutil examine -d {b} -r platform 2>&1")
        cards.append(dict(bdf=b, serial=rd(f"{x}/serial_num") if x else None,
                          numa_node=rd(f"/sys/bus/pci/devices/{b}/numa_node"),
                          shell=(re.search(r"XSA Name\s*:\s*(\S+)", ex) or [None, None])[1],
                          logic_uuid=(re.search(r"Logic UUID\s*:\s*(\S+)", ex) or [None, None])[1]))
    bit = {}
    for k, p in XCLBINS.items():
        p = os.path.join(ROOT, p)
        if os.path.exists(p):
            info = sh(xrt + f"xclbinutil --info -i {p} 2>/dev/null")
            bit[k] = dict(path=os.path.relpath(p, ROOT), sha256=sha(p),
                          uuid=(re.search(r"UUID \(xclbin\):\s*(\S+)", info) or [None, None])[1],
                          kernel_clocks_mhz=re.findall(r"Frequency:\s*(\d+) MHz", info))
    py = os.path.join(os.path.dirname(ROOT), "envs", "fpga", "bin", "python")
    vers = sh(f"{py} -c \"import numpy, scipy, qiskit, qiskit_aer, sys; print(sys.version.split()[0], numpy.__version__, "
              f"scipy.__version__, qiskit.__version__, qiskit_aer.__version__)\"").split()
    man = dict(captured=time.strftime("%Y-%m-%dT%H:%M:%S%z"), host=socket.gethostname(), kernel=platform.release(),
               os=sh("lsb_release -ds"), cpu=sh("lscpu | grep 'Model name' | cut -d: -f2").strip(),
               logical_cpus=os.cpu_count(), sockets=sh("lscpu | grep '^Socket(s)' | cut -d: -f2").strip(),
               cores_per_socket=sh("lscpu | grep 'Core(s) per socket' | cut -d: -f2").strip(),
               numa=sh("lscpu | grep 'NUMA node[0-9] CPU' "), mem_gib=sh("free -g | awk '/Mem:/{print $2}'"),
               governor=rd("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
               xrt=sh(xrt + "xbutil --version 2>/dev/null | grep -E 'Version|Branch|Hash' | tr -s ' '"),
               vitis="2023.2", python_fpga_env=dict(zip(["python", "numpy", "scipy", "qiskit", "qiskit_aer"], vers)),
               cards=cards, bitstreams=bit,
               git=dict(code=sh(f"git -C {ROOT} rev-parse HEAD"),
                        branch=sh(f"git -C {ROOT} rev-parse --abbrev-ref HEAD")))
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(man, open(os.path.join(ROOT, "results", "hardware_manifest.json"), "w"), indent=1)
    print(json.dumps(man, indent=1)[:2500])


if __name__ == "__main__":
    main()
