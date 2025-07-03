from pathlib import Path

import numpy as np
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

def test_consistency_iter(
    tar_path: Path,
    raw_pcap_path: Path
):
    source_tar = PCLVideoReader(tar_path)
    source_pcap = ouster.sdk.pcap.pcap_scan_source.PcapScanSource(str(raw_pcap_path.absolute())).single_source(0)

    pcap_iter = iter(source_pcap)
    it_num = 0
    for tar_packet in source_tar:
        pcap_packet = next(pcap_iter)

        # Check fields are correct
        for key in tar_packet.keys():
            np.testing.assert_allclose(
                tar_packet[key],
                pcap_packet.field(key),
                err_msg=f"For field {key}"
            )

        # Check other properties
        for prop in [
            "timestamp",
            "alert_flags",
            "packet_timestamp",
            "timestamp",
        ]:

            pass

        it_num += 1