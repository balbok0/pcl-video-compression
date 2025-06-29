import pickle
import tarfile
from os import PathLike
from pathlib import Path
from typing import Iterator

import ouster.cli
import ouster.cli.core
import ouster.sdk
import ouster.sdk.client

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

        cv2.
        pass
