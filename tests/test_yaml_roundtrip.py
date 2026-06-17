from pathlib import Path

import numpy as np
import ouster.sdk.pcap

import main
from pcl_compression.reader import PCLVideoReader

PCAP = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap")
JSON = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241.json")
N = 4

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


def test_yaml_tar_reconstructs_all_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main.ouster.sdk.pcap.pcap_scan_source, "PcapScanSource", _Ctor
    )
    tar = tmp_path / "out.tar"
    main.create_tar_from_pcap(pcap_file=PCAP, output_file_path=tar,
                              json_path=JSON, qp_level=0)

    src = _real(str(PCAP.absolute())).single_source(0)
    truth = []
    for i, pkt in enumerate(src):
        if i >= N:
            break
        d = {f: pkt.field(f) for f in pkt.fields}
        d["pose"] = pkt.pose.reshape(-1, 16)
        truth.append(d)

    reader = PCLVideoReader(tar)
    for i, scan in enumerate(reader):
        for field, expected in truth[i].items():
            assert np.array_equal(expected, scan[field]), field
    reader.close()
