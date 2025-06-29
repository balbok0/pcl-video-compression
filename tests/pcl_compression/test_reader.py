from pathlib import Path

import ouster
import ouster.sdk

from pcl_compression.reader import PCLVideoReader


def test_pcl_video_reader_constructor(tar_path: Path):
    pvr = PCLVideoReader(tar_path)


def test_consistency_properties(
    tar_path: Path,
    raw_pcap_path: Path,
):
    source_pcap = ouster.sdk.pcap.pcap_scan_source.PcapScanSource(str(raw_pcap_path.absolute())).single_source(0)
    source_tar = PCLVideoReader(tar_path)

    for field_name in [
        # 'clip',
        # 'close',
        'field_types',
        'fields',
        'is_indexed',
        'is_live',
        'is_seekable',
        # 'mask',
        'metadata',
        # 'reduce',
        'scans_num',
        # 'slice',
    ]:
        assert getattr(source_pcap, field_name) == getattr(source_tar, field_name)


    # print(source)