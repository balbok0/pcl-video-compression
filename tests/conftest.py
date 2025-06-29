import pytest
from pathlib import Path

TESTS_ROOT_PATH = Path(__file__).parent
AUX_FILES_PATH = TESTS_ROOT_PATH / "aux_files"


@pytest.fixture
def tar_path() -> Path:
    return AUX_FILES_PATH / "out.tar"

@pytest.fixture
def raw_pcap_path() -> Path:
    return AUX_FILES_PATH / "small-pcap-test.pcap"

@pytest.fixture
def raw_json_path() -> Path:
    return AUX_FILES_PATH / "small-pcap-test.json"
