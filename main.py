"""Streamlined PCL -> video conversion.

Same idea as ``main.py`` (decompose each LiDAR field into byte-split grayscale
images, encode each as H.265, bundle into a tar) but without the intermediate
PNG-on-disk step. Frames are streamed straight into one ffmpeg subprocess per
field/channel via stdin, so the pcap is read exactly once and no per-scan image
files ever touch disk.

The non-image auxiliary fields (timestamp, packet_timestamp, status,
alert_flags) keep the per-scan .npy behaviour from ``main.py`` for now.

The output tar is structurally identical to ``main.py``'s, so ``PCLVideoReader``
reads it unchanged.
"""

import argparse
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
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
        result[field_name] = getattr(field_type, field_name)
    return result


@dataclass(slots=True)
class AdditionalMeta:
    num_scans: int
    field_types: list[ouster.sdk.client.data.FieldTypes]
    fields_to_channels: dict[str, list[tuple[int, np.dtype]]]

    def __iter__(self):
        for slot in self.__slots__:
            value = getattr(self, slot)
            if slot == "field_types":
                value = [_field_type_to_dict(ft) for ft in value]
            yield slot, value


def _meta_to_yaml_doc(meta: "AdditionalMeta") -> dict:
    """Convert AdditionalMeta into plain YAML-serializable types."""
    d = dict(meta)
    field_types = []
    for ft in d["field_types"]:
        field_types.append({
            "name": str(ft["name"]),
            "element_type": np.dtype(ft["element_type"]).name,   # e.g. "uint32"
            "extra_dims": list(ft["extra_dims"]),
            "field_class": int(ft["field_class"]),               # Ouster FieldClass -> int
        })
    fields_to_channels = {
        field: [[int(c), np.dtype(dt).name] for c, dt in channels]
        for field, channels in d["fields_to_channels"].items()
    }
    return {
        "num_scans": int(d["num_scans"]),
        "field_types": field_types,
        "fields_to_channels": fields_to_channels,
    }


def is_empty_folder(p: Path) -> bool:
    if not (p.exists() and p.is_dir()):
        return False

    for _ in p.glob("*"):
        return False

    return True


# Fields that are stored as raw per-scan .npy rather than encoded as video.
AUX_FIELDS = ["timestamp", "packet_timestamp", "status", "alert_flags"]
DEFAULT_FRAME_RATE = 10.0


def _nominal_frame_rate(json_path: Path) -> float:
    """Derive a nominal fps from the sensor's lidar mode (e.g. '2048x10' -> 10).

    fps is only container metadata here -- reconstruction is by frame index and
    true per-scan timestamps are stored separately -- so a nominal value lets us
    open encoders up front without a pre-pass over the pcap.
    """
    try:
        m = re.search(r'"lidar_mode"\s*:\s*"\d+x(\d+)"', json_path.read_text())
        if m:
            return float(m.group(1))
    except OSError:
        pass
    return DEFAULT_FRAME_RATE


class _ChannelEncoder:
    """One ffmpeg/libx265 subprocess fed raw grayscale frames over stdin."""

    def __init__(self, out_path: Path, width: int, height: int,
                 frame_rate: float, qp_level: int, gop_size: int | None):
        args = [
            "ffmpeg", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "gray",
            "-s", f"{width}x{height}",
            "-framerate", f"{frame_rate}",
            "-i", "-",
            "-c:v", "libx265",
            "-preset", "ultrafast",
            "-qp", f"{qp_level}",
        ]

        x265_params = []
        if qp_level == 0:
            x265_params.append("lossless=1")
        if gop_size is not None:
            x265_params.append(f"keyint={gop_size}")
        if x265_params:
            args.extend(["-x265-params", ":".join(x265_params)])

        args.extend(["-y", str(out_path.absolute())])
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE)

    def write(self, frame: np.ndarray) -> None:
        # tobytes() yields C-order bytes regardless of the (strided) view.
        self._proc.stdin.write(frame.tobytes())

    def close(self) -> None:
        self._proc.stdin.close()
        if self._proc.wait() != 0:
            raise RuntimeError("ffmpeg encoder exited with a non-zero status")


def create_tar_from_pcap(
    pcap_file: Path,
    output_file_path: Path | None = None,
    work_dir: Path | None = None,
    json_path: Path | None = None,
    qp_level: int = 0,
    gop_size: int | None = None,
):
    is_work_dir_temp = work_dir is None
    work_dir = work_dir or Path(tempfile.mkdtemp())
    work_dir.mkdir(parents=True, exist_ok=True)

    if not is_empty_folder(work_dir):
        raise ValueError("Work directory is not empty. This will lead to weird results!")

    output_file_path = output_file_path or pcap_file.with_suffix(".tar")
    json_path = json_path or pcap_file.with_suffix(".json")
    frame_rate = _nominal_frame_rate(json_path)

    source = ouster.sdk.pcap.pcap_scan_source.PcapScanSource(
        str(pcap_file.absolute())
    ).single_source(0)

    encoders: dict[tuple[str, int], _ChannelEncoder] = {}
    fields_to_channels: dict[str, list[tuple[int, np.dtype]]] = defaultdict(list)
    num_packets = 0

    def stream_field(field: str, frame: np.ndarray, packet_ts: int) -> None:
        # u32|u16|u8 grid -> 4|2|1 grayscale u8 channels, mirroring main.py.
        element_type = frame.dtype  # original dtype, needed to reconstruct on read
        channels = frame[..., None].view(np.uint8)
        for channel in range(channels.shape[-1]):
            key = (field, channel)
            chan_frame = channels[..., channel]
            encoder = encoders.get(key)
            if encoder is None:
                height, width = chan_frame.shape
                encoder = _ChannelEncoder(
                    work_dir / f"{field}_ch{channel}.mp4",
                    width=width, height=height, frame_rate=frame_rate,
                    qp_level=qp_level, gop_size=gop_size,
                )
                encoders[key] = encoder
                fields_to_channels[field].append((channel, element_type))
            encoder.write(chan_frame)

    try:
        for packet in tqdm.tqdm(source, total=source.scans_num):
            packet_ts = packet.get_first_valid_packet_timestamp()
            if packet_ts == 0:
                continue
            num_packets += 1

            for field in packet.fields:
                stream_field(field, packet.field(field), packet_ts)
            stream_field("pose", packet.pose.reshape(-1, 16), packet_ts)

            for field_name in AUX_FIELDS:
                folder = work_dir / field_name
                folder.mkdir(parents=True, exist_ok=True)
                np.save(folder / f"{packet_ts}.npy", getattr(packet, field_name))
    finally:
        for encoder in encoders.values():
            encoder.close()

    add_meta = AdditionalMeta(
        num_scans=num_packets,
        field_types=source.field_types,
        fields_to_channels=fields_to_channels,
    )

    make_tarfile(work_dir, json_path, add_meta, output_file_path)

    if is_work_dir_temp:
        shutil.rmtree(work_dir)


def make_tarfile(
    work_dir: Path,
    json_path: Path,
    add_meta: AdditionalMeta,
    output_path: Path,
):
    """Bundle the encoded videos, aux arrays and metadata into a tar.

    Unlike main.make_tarfile this collects the .npy arrays from ``work_dir``
    (where this pipeline actually wrote them) rather than a hard-coded path.
    """
    with tarfile.TarFile(output_path, mode="w") as tf:
        for mp4_path in work_dir.glob("*.mp4"):
            tf.add(mp4_path, mp4_path.name)

        tf.add(json_path, "metadata.json")

        for npy_path in work_dir.rglob("*.npy"):
            tf.add(npy_path, npy_path.relative_to(work_dir))

        with tempfile.TemporaryDirectory() as tmpdir:
            f_name = Path(tmpdir) / "_pcl_video_metadata.yaml"
            with open(f_name, mode="w") as f:
                yaml.safe_dump(_meta_to_yaml_doc(add_meta), f, sort_keys=False)
            tf.add(f_name, f_name.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input_file", type=Path, default=None)
    parser.add_argument("-j", "--json-input", type=Path, default=None)
    parser.add_argument("--qp", type=int, default=0)
    parser.add_argument("--gop-size", type=int, default=None)
    args = parser.parse_args()

    input_file = args.input_file or Path(
        "data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap"
    )
    create_tar_from_pcap(
        input_file,
        json_path=args.json_input,
        qp_level=args.qp,
        gop_size=args.gop_size,
    )


if __name__ == "__main__":
    main()
