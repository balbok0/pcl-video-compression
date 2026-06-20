"""Compare the C++ pcl2tar output against main.py on the first N scans.

The C++ CLI has no scan limit (it converts the whole pcap); main.py is limited
to the first N scans here. We compare only the first N decoded frames of each
video member, plus the metadata.
"""
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import av
import numpy as np
import ouster.sdk.pcap
import yaml

import main  # noqa: E402

N = 8
PCAP = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap")
JSON = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241.json")
CPP = Path("cpp_project/build/pcl2tar")

_real = ouster.sdk.pcap.pcap_scan_source.PcapScanSource


class _Lim:
    def __init__(self, inner): self._i = inner
    def __iter__(self):
        it = iter(self._i)
        for _ in range(N):
            yield next(it)
    @property
    def scans_num(self): return N
    def __getattr__(self, n): return getattr(self._i, n)


class _Ctor:
    def __init__(self, *a, **k): self._s = _real(*a, **k)
    def single_source(self, i): return _Lim(self._s.single_source(i))


def decode_all(tf, name):
    with tempfile.TemporaryDirectory() as d:
        tf.extract(name, d)
        c = av.open(str(Path(d) / name))
        frames = np.stack([f.to_ndarray(channel_last=True) for f in c.decode(0)])
        c.close()
    return frames


def run():
    main.ouster.sdk.pcap.pcap_scan_source.PcapScanSource = _Ctor
    py_tar = Path(tempfile.mktemp(suffix=".tar"))
    main.create_tar_from_pcap(pcap_file=PCAP, output_file_path=py_tar,
                              json_path=JSON, qp_level=0)

    cpp_tar = PCAP.with_suffix(".tar")
    subprocess.run([str(CPP), "-i", str(PCAP), "-j", str(JSON), "--qp", "0"],
                   check=True, stdout=subprocess.DEVNULL)

    ok = True
    with tarfile.open(py_tar) as tp, tarfile.open(cpp_tar) as tc:
        names_p = {n for n in tp.getnames() if n.endswith(".mp4")}
        names_c = {n for n in tc.getnames() if n.endswith(".mp4")}
        if names_p != names_c:
            print("MEMBER MISMATCH", names_p ^ names_c)
            ok = False
        for name in sorted(names_p & names_c):
            a = decode_all(tp, name)[:N]
            b = decode_all(tc, name)[:N]
            if not np.array_equal(a, b):
                print(f"VIDEO MISMATCH {name}  {a.shape} vs {b.shape}")
                ok = False

        mp = yaml.safe_load(tp.extractfile("_pcl_video_metadata.yaml"))
        mc = yaml.safe_load(tc.extractfile("_pcl_video_metadata.yaml"))
        norm = lambda d: {k: sorted(v) for k, v in d["fields_to_channels"].items()}
        if norm(mp) != norm(mc):
            print("fields_to_channels MISMATCH")
            ok = False

    print(f"compared {len(names_p & names_c)} videos")
    print("EQUIVALENT (first %d frames)" % N if ok else "DIFFERENCES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
