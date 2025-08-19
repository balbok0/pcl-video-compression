import argparse
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import ouster.sdk

from main import create_tar_from_pcap
from pcl_compression.reader import PCLVideoReader

PCAP_FILE = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap")
JSON_FILE = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241.json")
NUM_TEST_RUNS = 1


def benchtest_qp(
    qp_level: int,
    pcap_file: Path = PCAP_FILE,
    json_file: Path = JSON_FILE,
) -> tuple[list[int], list[Path]]:
    durations = []
    file_paths = []

    for run_idx in range(NUM_TEST_RUNS):
        run_file_path = Path(f"bench_test_qp_{qp_level}_run_{run_idx}.tar")

        start_time = time.time_ns()
        create_tar_from_pcap(
            pcap_file=pcap_file,
            output_file_path=run_file_path,
            json_path=json_file,
            qp_level=qp_level,
        )
        end_time = time.time_ns()
        durations.append(end_time - start_time)

        file_paths.append(run_file_path)
    return durations, file_paths


def get_mean_abs_error_per_field(
    tar_path: Path,
    raw_pcap_path: Path
):
    source_tar = PCLVideoReader(tar_path)
    source_pcap = ouster.sdk.pcap.pcap_scan_source.PcapScanSource(str(raw_pcap_path.absolute())).single_source(0)

    pcap_iter = iter(source_pcap)
    errors_per_field = defaultdict(list)

    for tar_packet in source_tar:
        pcap_packet = next(pcap_iter)

        for field in source_tar.fields:
            errors_per_field[field].append(
                np.mean(
                    100. * np.abs(pcap_packet.field(field) - tar_packet[field])
                    / (1e-6 + np.abs(pcap_packet.field(field)))
                )
            )

    return {
        f: np.mean(errs)
        for f, errs in errors_per_field.items()
    }



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "-p", "--input", type=Path, default=PCAP_FILE, help="pcap file")
    parser.add_argument("-j", "--json-input", type=Path, default=JSON_FILE, help="metadata json file associated with pcap")

    args = parser.parse_args()

    times_per_qp: dict[int, int] = {}
    paths_per_qp: dict[int, Path] = {}

    for qp in [0, 4, 10, 25]:
        timing, paths = benchtest_qp(qp, args.input, args.json_input)
        times_per_qp[qp] = timing
        paths_per_qp[qp] = paths

    for qp in times_per_qp.keys():
        print("=======================================")
        print(f"{qp = }")
        print(f"{times_per_qp[qp][0] = }")
        print([f.stat().st_size for f in paths_per_qp[qp]][0])
        print(get_mean_abs_error_per_field(
            paths_per_qp[qp][0],
            args.input,
        ))
        print("=======================================")



if __name__ == "__main__":
    main()