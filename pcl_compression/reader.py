import pickle
import shutil
import tarfile
import tempfile
from os import PathLike
from pathlib import Path
from typing import Iterator

import ouster.cli
import ouster.cli.core
import ouster.sdk
import ouster.sdk.client

import av
import cv2
import yaml
import numpy as np
# from ouster.sdk. import Field

FieldType = None


# Things to implement:
# 'clip'
# 'close'
# 'field_types'
# 'fields'
# 'is_indexed'
# 'is_live'
# 'is_seekable'
# 'mask'
# 'metadata'
# 'reduce'
# 'scans_num'
# 'slice'


class PCLVideoReader:
    def __init__(
        self,
        file_path: PathLike
    ):
        self.file_path = Path(file_path)

        self.tar_file = tarfile.TarFile(self.file_path, mode="r")

        buf = self.tar_file.extractfile("_pcl_video_metadata.pkl")
        self._pcl_vid_metadata = pickle.load(buf)
        self._field_types = []
        self._fields = []
        for ft_dict in self._pcl_vid_metadata["field_types"]:
            self.field_types.append(ouster.sdk.client.data.FieldType(
                name=ft_dict["name"],
                dtype=ft_dict["element_type"].type,
                extra_dims=ft_dict["extra_dims"],
                field_class=ft_dict["field_class"],
            ))
            self._fields.append(ft_dict["name"])


        buf = self.tar_file.extractfile("metadata.json")
        self.sensor_info_meta = ouster.sdk.client.SensorInfo(buf.read())


    def fields(self):
        print(self.tar_file.getmembers())
        pass

    def clip(self, fields: list[str], lower: int, upper: int) -> 'PCLVideoReader':
        print

    def close(self):
        self.tar_file.close()

    @property
    def field_types(self) -> list[ouster.sdk.client.data.FieldTypes]:
        return self._field_types

    @property
    def fields(self) -> list[str]:
        return self._fields

    @property
    def scans_num(self) -> int | None:
        return self._pcl_vid_metadata.get("scans_num")

    @property
    def is_seekable(self) -> bool:
        return False

    @property
    def is_indexed(self) -> bool:
        return False

    @property
    def is_live(self) -> bool:
        return False

    @property
    def metadata(self) -> ouster.sdk.client.SensorInfo:
        """Return metadata from the underlying PacketSource."""
        return self.sensor_info_meta

    def slice(self, key: slice) -> 'PCLVideoReader':
        """Constructs a ScanSource matching the specified slice"""
        ...

    def clip(self, fields: list[str], lower: int, upper: int) -> 'PCLVideoReader':
        """Constructs a ScanSource matching the specified clip options"""
        ...

    def reduce(self, beams: int) -> 'PCLVideoReader':
        """Constructs a reduced ScanSource matching the beam count"""
        ...

    def __del__(self):
        self.close()


    def __iter__(self) -> Iterator[list[ouster.sdk.client.LidarScan | None]]:
        fields = self.fields
        # Sort fields and channels accordingly
        fields_channels = self._pcl_vid_metadata["fields_to_channels"]
        for field in fields_channels.keys():
            fields_channels[field] = list(sorted(fields_channels[field]))

        # Proof of concept. Should read from file directly
        td = tempfile.gettempdir()
        td_path = Path(td)

        fields_vid_captures = {}
        for field, channels in fields_channels.items():
            field_vids = []
            for c, _ in channels:
                f_name = f"{field}_ch{c}.mp4"
                self.tar_file.extract(f"{field}_ch{c}.mp4", td_path)

                container = av.open(td_path / f_name, mode="r")
                # vc = cv2.VideoCapture(str((td_path / f_name).absolute()))
                # vc.set(cv2.CAP_PROP_CONVERT_RGB, 0)
                # vc.set(cv2.CAP_PROP_CONVERT_RGB, 0)
                field_vids.append(container.decode(0))


            fields_vid_captures[field] = field_vids
        return PacketIterator(
            field_vid_captures=fields_vid_captures,
            fields=self.field_types,
            temp_dir=td_path
        )


class PacketIterator:
    def __init__(
        self,
        field_vid_captures: dict[str, list[Iterator[av.VideoFrame]]],
        fields: ouster.sdk.client.data.FieldTypes,
        temp_dir: Path
    ):

        self.field_vid_captures = field_vid_captures
        self.fields = {
            field.name: field
            for field in fields
        }
        self.temp_dir = temp_dir

    def __next__(self):
        frames = {}
        for field, vids in self.field_vid_captures.items():
            field_frames = [
                next(vid).to_ndarray(channel_last=True)
                for vid in vids
            ]

            if len(field_frames) == 1:
                frames[field] = field_frames[0]
                continue

            cat_view = np.concatenate([a[..., np.newaxis] for a in field_frames], axis=-1)
            frames[field] = cat_view.view(self.fields[field].element_type)[..., 0]
        return frames

    def __del__(self):
        shutil.rmtree(self.temp_dir)

"""
Packet class

methods:
'add_field'
'alert_flags'
'complete'
'del_field'
'field'
'field_class'
'field_types'
'fields'
'frame_id'
'frame_status'
'get_first_valid_column_timestamp'
'get_first_valid_packet_timestamp'
'h'
'has_field'
'measurement_id'
'packet_count'
'packet_timestamp'
'pose'
'sensor_info'
'shot_limiting'
'shot_limiting_countdown'
'shutdown_countdown'
'status'
'thermal_shutdown'
'timestamp'
'w'
"""