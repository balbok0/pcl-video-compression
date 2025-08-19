import argparse
import subprocess
import tarfile
import tempfile
import pickle
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import ouster
import ouster.sdk
import ouster.sdk.client
import ouster.sdk.pcap
import tqdm

def _field_type_to_dict(field_type):
    result = {}
    for field_name in [
        "name",
        "element_type",
        "extra_dims",
        "field_class",
    ]:
        # result[field_name] = str(getattr(field_type, field_name))
        result[field_name] = getattr(field_type, field_name)
    return result

@dataclass(slots=True)
class AdditionalMeta:
    num_scans: int
    field_types: list[ouster.sdk.client.data.FieldTypes]
    fields_to_channels: dict[str, list[tuple[int, np.dtype]]]


    def __iter__(self):
        result = {}
        for slot in self.__slots__:
            value = getattr(self, slot)
            if slot == "field_types":
                value = [
                    _field_type_to_dict(ft)
                    for ft in value
                ]
            yield slot, value


def is_empty_folder(p: Path) -> bool:
    if not (p.exists() and p.is_dir()):
        return False

    for _ in p.glob("*"):
        return False

    return True


def create_tar_from_pcap(
    pcap_file: Path,
    output_file_path: Path | None = None,
    work_dir: Path | None = None,
    json_path: Path | None = None,
    qp_level: int = 0,
):
    is_work_dir_temp = work_dir is None
    work_dir = work_dir or Path(tempfile.mkdtemp())
    work_dir.mkdir(parents=True, exist_ok=True)

    if not is_empty_folder(work_dir):
        raise ValueError("Work directory is not empty. This will lead to weird results!")

    output_file_path = output_file_path or pcap_file.with_suffix(".tar")
    json_path = json_path or pcap_file.with_suffix(".json")

    fields_channels, frame_rate, add_meta = make_png_folders(
        pcap_file,
        out_folder_path=work_dir
    )

    make_videos(
        fields_channels,
        frame_rate,
        root_folder_path=work_dir,
        qp_level=qp_level,
    )

    make_tarfile(
        packets_path=work_dir,
        json_path=json_path,
        add_meta=add_meta,
        output_path=output_file_path
    )

    if is_work_dir_temp:
        shutil.rmtree(work_dir)


def parse_frame(
    frame: np.ndarray,
    packet_ts: int,
    field: str,
    out_folder: Path,
) -> set[tuple[str, str]]:
    # Convert a u32|16|8 -> 4x|2x|1xu8 channels
    frame = frame[..., None]
    # if frame.dtype == np.uint8:
    #     # Don't do anything
    #     pass
    # else:
    #     # Convert into u832 into 2xu16

    # Convert everything into u8. This allows from h265 encoding
    frame = frame.view(np.uint8)

    fields_channels_types = set()
    for channel in range(frame.shape[-1]):
        fields_channels_types.add((field, channel, frame.dtype))
        success, png_bytes = cv2.imencode(".png", frame[..., channel])
        assert success
        png_path = Path(out_folder / field / f"ch{channel}" / f"{packet_ts}.png")
        png_path.parent.mkdir(parents=True, exist_ok=True)
        with open(png_path, mode="wb") as f:
            f.write(png_bytes)
    return fields_channels_types


def make_png_folders(
    pcap_file: Path,
    out_folder_path: Path = Path("data/packets/")
):
    source = ouster.sdk.pcap.pcap_scan_source.PcapScanSource(str(pcap_file.absolute())).single_source(0)


    fields_channels_types = set()
    timestamp_start = np.iinfo(np.uint64).max
    timestamp_stop = 0
    num_packets = 0
    for packet in tqdm.tqdm(source, total=source.scans_num):
        packet_ts = packet.get_first_valid_packet_timestamp()
        if packet_ts == 0:
            continue

        num_packets += 1
        timestamp_start = min(packet_ts, timestamp_start)
        timestamp_stop = max(packet_ts, timestamp_stop)

        for field in packet.fields:
            frame = packet.field(field)
            fields_channels_types.update(parse_frame(frame, packet_ts, field, out_folder_path))


        parse_frame(packet.pose.reshape(-1, 16), packet_ts, "pose", out_folder_path)

        for field_name in ["timestamp", "packet_timestamp", "status", "alert_flags"]:
            folder_name = out_folder_path / field_name
            folder_name.mkdir(parents=True, exist_ok=True)
            np.save(folder_name / f"{packet_ts}.npy", getattr(packet, field_name))
        # fields_channels_types.update(parse_frame(packet.status[..., np.newaxis], packet_ts, "status"))
        # fields_channels_types.update(parse_frame(packet.packet_timestamp[..., np.newaxis], packet_ts, "packet_timestamp"))
        # fields_channels_types.update(parse_frame(packet.alert_flags[..., np.newaxis], packet_ts, "alert_flags"))
        # fields_channels_types.update(parse_frame(packet.timestamp[..., np.newaxis], packet_ts, "timestamp"))
        # fields_channels_types.update(parse_frame(packet.status[..., np.newaxis], packet_ts, "status"))
        # fields_channels_types.update(parse_frame(packet.packet_timestamp[..., np.newaxis], packet_ts, "packet_timestamp"))
        # fields_channels_types.update(parse_frame(packet.alert_flags[..., np.newaxis], packet_ts, "alert_flags"))

    frame_rate = (timestamp_stop - timestamp_start) / 1e7 / num_packets
    print(f"FPS: {frame_rate}")

    fields_to_channels = defaultdict(list)
    for f, c, t in fields_channels_types:
        fields_to_channels[f].append((c, t))

    add_meta = AdditionalMeta(
        num_scans=num_packets,
        field_types=source.field_types,
        fields_to_channels=fields_to_channels
    )

    return fields_channels_types, frame_rate, add_meta


def make_videos(
    fields_channels: set[tuple[str, int, np.dtype]],
    frame_rate: float,
    root_folder_path: Path = Path("data/packets/"),
    qp_level: int = 0
):
    for field, channel, dtype in fields_channels:
        folder_path = root_folder_path / field / f"ch{channel}"
        out_path_video_path = root_folder_path / f"{field}_ch{channel}.mp4"

        sp_args = [
            "ffmpeg",
            "-framerate",
            f"{frame_rate}",
            "-pattern_type",
            "glob",
            "-i",
            f"{folder_path}/*.png",
            "-pix_fmt",
            "gray",
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-qp",
            f"{qp_level}",
        ]

        if qp_level == 0:
            sp_args.extend([
                "-x265-params",
                "lossless=1",
            ])

        sp_args.extend([
            "-y",
            str(out_path_video_path.absolute()),
        ])

        subprocess.check_output(sp_args)


def make_tarfile(
    packets_path: Path,
    json_path: Path,
    add_meta: AdditionalMeta,
    output_path: Path | None = None,
):
    output_path = output_path or packets_path / "out.tar"
    with tarfile.TarFile(output_path, mode="w") as tf:
        for mp4_path in packets_path.glob("*.mp4"):
            tf.add(mp4_path, mp4_path.name)

        # Add basic metadata
        tf.add(json_path, "metadata.json")

        # Add npy arrays
        root_workdir = Path("data/packets")
        for npy_path in root_workdir.rglob("*.npy"):
            tf.add(npy_path, npy_path.relative_to(root_workdir))

        # Write additional meta to temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            f_name = Path(tmpdir) / "_pcl_video_metadata.pkl"
            with open(f_name, mode="wb") as f:
                pickle.dump(dict(add_meta), f)

            tf.add(f_name, f_name.name)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("-i", "--input_file", type=Path, default=None)
    args = parser.parse_args()

    input_file = args.input_file or "data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap"
    create_tar_from_pcap(input_file)

if __name__ == "__main__":
    main()
