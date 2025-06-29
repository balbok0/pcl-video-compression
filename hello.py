import shutil
import subprocess
import tarfile
import tempfile
import pickle
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import ouster
import ouster.sdk
import ouster.sdk.client
import ouster.sdk.pcap
import tqdm
import yaml

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



def main_pcap():
    # pcap_file = Path(__file__).parent / "data" / "OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap"
    pcap_file = Path(__file__).parent / "tests" / "aux_files" / "small-pcap-test.pcap"

    fields_channels, frame_rate, add_meta = make_png_folders(pcap_file)

    make_videos(fields_channels, frame_rate)

    make_tarfile(Path("data/packets/"), pcap_file.with_suffix(".json"), add_meta)


def parse_frame(
    frame: np.ndarray,
    packet_ts: int,
    field: str,
) -> set[tuple[str, str]]:
    # Convert a u32|16|8 -> 4x|2x|1xu8 channels
    frame = frame[..., None]
    if frame.dtype == np.uint8:
        # Don't do anything
        pass
    else:
        # Convert u32 into 2xu16
        frame = frame.view(np.uint16)

    fields_channels = set()
    for channel in range(frame.shape[-1]):
        fields_channels.add((field, channel))
        success, png_bytes = cv2.imencode(".png", frame[..., channel])
        assert success
        png_path = Path(f"data/packets/{field}/ch{channel}/{packet_ts}.png")
        png_path.parent.mkdir(parents=True, exist_ok=True)
        with open(png_path, mode="wb") as f:
            f.write(png_bytes)
    return fields_channels


def make_png_folders(pcap_file: Path):
    source = ouster.sdk.pcap.pcap_scan_source.PcapScanSource(str(pcap_file.absolute())).single_source(0)


    fields_channels = set()
    timestamp_start = np.iinfo(np.uint64).max
    timestamp_stop = 0
    num_packets = 0
    for packet in tqdm.tqdm(source, total=source.scans_num):
        packet_ts = packet.packet_timestamp.min()
        if packet_ts == 0:
            continue

        num_packets += 1
        timestamp_start = min(packet_ts, timestamp_start)
        timestamp_stop = max(packet_ts, timestamp_stop)

        for field in packet.fields:
            frame = packet.field(field)
            fields_channels.update(parse_frame(frame, packet_ts, field))

        parse_frame(packet.timestamp, packet_ts, "timestamp")

    frame_rate = (timestamp_stop - timestamp_start) / 1e7 / num_packets
    print(f"FPS: {frame_rate}")

    add_meta = AdditionalMeta(
        num_scans=num_packets,
        field_types=source.field_types,
    )

    return fields_channels, frame_rate, add_meta


def make_videos(
    fields_channels: set[tuple[str, str]],
    frame_rate: float,
):
    for field, channel in fields_channels:
        folder_path = f"data/packets/{field}/ch{channel}"
        subprocess.run(
            [
                "ffmpeg",
                "-framerate",
                f"{frame_rate}",
                "-pattern_type",
                "glob",
                "-i",
                f"{folder_path}/*.png",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-qp",
                "0",
                "-y",
                f"data/packets/{field}_ch{channel}.mp4",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        shutil.rmtree(folder_path)


def make_tarfile(
    packets_path: Path,
    json_path: Path,
    add_meta: AdditionalMeta
):

    # packets_path = Path("data/packets/")
    with tarfile.TarFile(packets_path / "out.tar", mode="w") as tf:
        for mp4_path in packets_path.glob("*.mp4"):
            tf.add(mp4_path)

        tf.add(json_path, "metadata.json")

        # Write additional meta to temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            f_name = Path(tmpdir) / "_pcl_video_metadata.pkl"
            with open(f_name, mode="wb") as f:
                pickle.dump(dict(add_meta), f)

            tf.add(f_name, f_name.name)


def main():
    # main_bag()
    main_pcap()
    # main_ply()

if __name__ == "__main__":
    main()
