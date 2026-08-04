"""Benchmark the C++ pcl2tar binary, mirroring benchmark.py's output.

Runs pcl2tar across QP levels and reports, per QP: conversion time, output tar
size, size reduction vs the source pcap, and per-field mean absolute error
(reusing benchmark.py's metric, which reads the C++ tar via PCLVideoReader).

Usage:
    uv run python benchmark_cpp.py [-i <pcap>] [-j <json>]

Note: pcl2tar writes to <pcap-basename>.tar (a fixed path), so each run's
output is moved to bench_cpp_qp_<qp>.tar before the next run.
"""
import argparse
import subprocess
import time
from pathlib import Path

from benchmark import get_mean_abs_error_per_field

PCAP_FILE = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap")
JSON_FILE = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241.json")
BIN = Path("cpp_project/build/pcl2tar")
QP_LEVELS = [0, 10]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "-p", "--input", type=Path, default=PCAP_FILE, help="pcap file")
    parser.add_argument("-j", "--json-input", type=Path, default=JSON_FILE, help="metadata json file")
    parser.add_argument("--bin", type=Path, default=BIN, help="path to pcl2tar binary")
    args = parser.parse_args()

    if not args.bin.exists():
        raise SystemExit(f"pcl2tar binary not found at {args.bin}; build it first "
                         f"(cmake --build cpp_project/build --target pcl2tar)")

    orig_size = args.input.stat().st_size

    for qp in QP_LEVELS:
        start_time = time.time_ns()
        subprocess.run(
            [str(args.bin), "-i", str(args.input), "-j", str(args.json_input), "--qp", str(qp)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        duration_ns = time.time_ns() - start_time

        produced = args.input.with_suffix(".tar")
        saved = Path(f"bench_cpp_qp_{qp}.tar")
        produced.replace(saved)
        size_bytes = saved.stat().st_size

        print("=======================================")
        print("impl_name = 'cpp'")
        print(f"{qp = }")
        print(f"duration_ns = {duration_ns}")
        print(f"size_bytes = {size_bytes}")
        print(f"reduction_pct = {100 * (1 - size_bytes / orig_size):.2f}")
        print(get_mean_abs_error_per_field(saved, args.input))
        print("=======================================")


if __name__ == "__main__":
    main()
