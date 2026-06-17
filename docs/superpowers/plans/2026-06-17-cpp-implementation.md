# C++ Implementation Matching `main.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a C++ CLI that converts an Ouster pcap into the same `.tar` artifact `main.py` produces (byte-exact decoded frames, equivalent YAML metadata), with the encode/bundle logic in a reusable, Ouster-free core library.

**Architecture:** Three units. (A) Migrate the Python metadata file from pickle to YAML so both languages share a neutral format. (B) A C++ core library `pclvideo` that takes per-scan field buffers, byte-splits multi-byte fields into uint8 channels, encodes each channel to H.265 via libavcodec, and bundles videos + aux `.npy` + `metadata.json` + `metadata.yaml` into a POSIX ustar tar. (C) A `pcl2tar` CLI front-end that reads the pcap with the Ouster C++ SDK (FetchContent) and drives the core.

**Tech Stack:** Python 3.12 (uv, pyyaml, ouster-sdk, PyAV), C++20, CMake (FetchContent), libavcodec/libavformat/libavutil (Homebrew ffmpeg), doctest (C++ unit tests), ouster-sdk C++ (CLI only).

**Spec:** `docs/superpowers/specs/2026-06-17-cpp-implementation-design.md`

**Conventions:**
- All C++ lives under `cpp_project/`. Core lib sources in `cpp_project/src/pclvideo/`, public headers in `cpp_project/include/pclvideo/`, CLI in `cpp_project/src/cli/`, tests in `cpp_project/tests/`.
- Build directory: `cpp_project/build/`. Configure once with `cmake -S cpp_project -B cpp_project/build`; build with `cmake --build cpp_project/build`.
- Run C++ tests with `ctest --test-dir cpp_project/build --output-on-failure`.
- The demo pcap/json are `data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap` and the matching `.json`.

---

## Phase A — Python metadata migration (pickle → YAML)

### Task A1: Switch the writer to YAML

**Files:**
- Modify: `main.py` (the `make_tarfile` function and the `import pickle` line)

- [ ] **Step 1: Add a YAML-serialization helper for the metadata dict**

In `main.py`, the `dict(add_meta)` produced by `AdditionalMeta.__iter__` contains numpy dtypes and an Ouster `field_class` enum that PyYAML cannot serialize directly. Add this helper near `_field_type_to_dict`:

```python
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
```

- [ ] **Step 2: Replace the pickle write with a YAML write in `make_tarfile`**

Replace the `import pickle` usage block at the end of `make_tarfile`:

```python
        with tempfile.TemporaryDirectory() as tmpdir:
            f_name = Path(tmpdir) / "_pcl_video_metadata.yaml"
            with open(f_name, mode="w") as f:
                yaml.safe_dump(_meta_to_yaml_doc(add_meta), f, sort_keys=False)
            tf.add(f_name, f_name.name)
```

Add `import yaml` to the imports and remove `import pickle` if now unused. Update the docstring note that mentioned `.pkl`.

- [ ] **Step 3: Run the writer on a few scans to confirm it produces the YAML member**

Run:
```bash
uv run python - <<'PY'
import tarfile, ouster.sdk.pcap, main
from pathlib import Path
_real = ouster.sdk.pcap.pcap_scan_source.PcapScanSource
class Lim:
    def __init__(s,i): s.i=i
    def __iter__(s):
        it=iter(s.i)
        for _ in range(4): yield next(it)
    @property
    def scans_num(s): return 4
    def __getattr__(s,n): return getattr(s.i,n)
class Ctor:
    def __init__(s,*a,**k): s.s=_real(*a,**k)
    def single_source(s,i): return Lim(s.s.single_source(i))
main.ouster.sdk.pcap.pcap_scan_source.PcapScanSource=Ctor
p=Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap")
j=Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241.json")
main.create_tar_from_pcap(pcap_file=p, output_file_path=Path("/tmp/_a.tar"), json_path=j, qp_level=0)
print(sorted(m.name for m in tarfile.TarFile("/tmp/_a.tar").getmembers() if "metadata" in m.name))
PY
```
Expected: output includes `_pcl_video_metadata.yaml` and `metadata.json`, and no `.pkl`.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "Write tar metadata as YAML instead of pickle"
```

### Task A2: Switch the reader to YAML

**Files:**
- Modify: `pcl_compression/reader.py` (`PCLVideoReader.__init__` and `__iter__`)
- Test: `tests/test_yaml_roundtrip.py` (create)

- [ ] **Step 1: Write the failing round-trip test**

Create `tests/test_yaml_roundtrip.py`:

```python
from pathlib import Path

import numpy as np
import ouster.sdk.pcap

import main
from pcl_compression.reader import PCLVideoReader

PCAP = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap")
JSON = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241.json")
N = 4

_real = ouster.sdk.pcap.pcap_scan_source.PcapScanSource


class _Lim:
    def __init__(self, inner): self._i = inner
    def __iter__(self):
        it = iter(self._i)
        for _ in range(N):
            yield next(it)
    @property
    def scans_num(self): return N
    def __getattr__(self, n): return getattr(self._i, n)


class _Ctor:
    def __init__(self, *a, **k): self._s = _real(*a, **k)
    def single_source(self, i): return _Lim(self._s.single_source(i))


def test_yaml_tar_reconstructs_all_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main.ouster.sdk.pcap.pcap_scan_source, "PcapScanSource", _Ctor
    )
    tar = tmp_path / "out.tar"
    main.create_tar_from_pcap(pcap_file=PCAP, output_file_path=tar,
                              json_path=JSON, qp_level=0)

    src = _real(str(PCAP.absolute())).single_source(0)
    truth = []
    for i, pkt in enumerate(src):
        if i >= N:
            break
        d = {f: pkt.field(f) for f in pkt.fields}
        d["pose"] = pkt.pose.reshape(-1, 16)
        truth.append(d)

    reader = PCLVideoReader(tar)
    for i, scan in enumerate(reader):
        for field, expected in truth[i].items():
            assert np.array_equal(expected, scan[field]), field
    reader.close()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_yaml_roundtrip.py -v`
Expected: FAIL — the reader still calls `pickle.load` on a now-absent `.pkl`, raising `KeyError`/`pickle` errors.

- [ ] **Step 3: Update `PCLVideoReader.__init__` to load YAML**

Replace the pickle load block in `__init__`:

```python
        buf = self.tar_file.extractfile("_pcl_video_metadata.yaml")
        self._pcl_vid_metadata = yaml.safe_load(buf)
        self._field_types = []
        self._fields = []
        for ft_dict in self._pcl_vid_metadata["field_types"]:
            self._field_types.append(ouster.sdk.client.data.FieldType(
                name=ft_dict["name"],
                dtype=np.dtype(ft_dict["element_type"]).type,
                extra_dims=tuple(ft_dict["extra_dims"]),
                field_class=ouster.sdk.client.data.FieldClass(ft_dict["field_class"]),
            ))
            self._fields.append(ft_dict["name"])
```

Remove `import pickle`. Confirm `import yaml` and `import numpy as np` are present (both already are).

- [ ] **Step 4: Update `__iter__`'s dtype fallback to parse dtype strings**

In `__iter__`, the `field_dtypes` fallback currently does `np.dtype(channels[0][1])`. The stored value is now a string like `"float64"`, which `np.dtype(...)` already accepts, so no change is needed there. Verify the line reads:

```python
                field_dtypes[field] = np.dtype(channels[0][1])
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_yaml_roundtrip.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pcl_compression/reader.py tests/test_yaml_roundtrip.py
git commit -m "Read tar metadata from YAML; add round-trip test"
```

---

## Phase B — C++ core library `pclvideo`

### Task B1: CMake skeleton + doctest harness

**Files:**
- Create: `cpp_project/CMakeLists.txt`
- Create: `cpp_project/include/pclvideo/dtype.hpp`
- Create: `cpp_project/src/pclvideo/dtype.cpp`
- Create: `cpp_project/tests/test_dtype.cpp`
- Create: `cpp_project/.gitignore`

- [ ] **Step 1: Write `cpp_project/.gitignore`**

```
build/
```

- [ ] **Step 2: Write the dtype unit (the smallest real unit) and its test first**

Create `cpp_project/include/pclvideo/dtype.hpp`:

```cpp
#pragma once
#include <cstddef>
#include <string>

namespace pclvideo {

enum class DType { U8, U16, U32, U64, I8, I16, I32, I64, F32, F64 };

// Byte width of one element.
std::size_t dtype_size(DType dt);

// NumPy name, e.g. "uint32" — matches numpy.dtype(...).name.
std::string dtype_numpy_name(DType dt);

// NumPy little-endian descr, e.g. "<u4" — for .npy headers.
std::string dtype_npy_descr(DType dt);

// Parse a numpy name ("uint32") into a DType. Throws std::invalid_argument.
DType dtype_from_numpy_name(const std::string& name);

}  // namespace pclvideo
```

Create `cpp_project/tests/test_dtype.cpp`:

```cpp
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include "pclvideo/dtype.hpp"

using namespace pclvideo;

TEST_CASE("dtype sizes and names") {
    CHECK(dtype_size(DType::U32) == 4);
    CHECK(dtype_size(DType::F64) == 8);
    CHECK(dtype_numpy_name(DType::U32) == "uint32");
    CHECK(dtype_numpy_name(DType::F64) == "float64");
    CHECK(dtype_npy_descr(DType::U32) == "<u4");
    CHECK(dtype_npy_descr(DType::F64) == "<f8");
    CHECK(dtype_from_numpy_name("uint16") == DType::U16);
}
```

- [ ] **Step 3: Write `cpp_project/CMakeLists.txt`**

```cmake
cmake_minimum_required(VERSION 3.24)
project(pclvideo_project LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(
  doctest
  GIT_REPOSITORY https://github.com/doctest/doctest.git
  GIT_TAG v2.4.11
)
FetchContent_MakeAvailable(doctest)

# Core library (no Ouster dependency).
add_library(pclvideo
  src/pclvideo/dtype.cpp
)
target_include_directories(pclvideo PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

enable_testing()
add_executable(test_dtype tests/test_dtype.cpp)
target_link_libraries(test_dtype PRIVATE pclvideo doctest::doctest)
add_test(NAME test_dtype COMMAND test_dtype)
```

- [ ] **Step 4: Implement `cpp_project/src/pclvideo/dtype.cpp`**

```cpp
#include "pclvideo/dtype.hpp"
#include <stdexcept>

namespace pclvideo {

std::size_t dtype_size(DType dt) {
    switch (dt) {
        case DType::U8: case DType::I8: return 1;
        case DType::U16: case DType::I16: return 2;
        case DType::U32: case DType::I32: case DType::F32: return 4;
        case DType::U64: case DType::I64: case DType::F64: return 8;
    }
    throw std::invalid_argument("unknown dtype");
}

std::string dtype_numpy_name(DType dt) {
    switch (dt) {
        case DType::U8: return "uint8";   case DType::U16: return "uint16";
        case DType::U32: return "uint32"; case DType::U64: return "uint64";
        case DType::I8: return "int8";    case DType::I16: return "int16";
        case DType::I32: return "int32";  case DType::I64: return "int64";
        case DType::F32: return "float32";case DType::F64: return "float64";
    }
    throw std::invalid_argument("unknown dtype");
}

std::string dtype_npy_descr(DType dt) {
    switch (dt) {
        case DType::U8: return "|u1";   case DType::U16: return "<u2";
        case DType::U32: return "<u4";  case DType::U64: return "<u8";
        case DType::I8: return "|i1";   case DType::I16: return "<i2";
        case DType::I32: return "<i4";  case DType::I64: return "<i8";
        case DType::F32: return "<f4";  case DType::F64: return "<f8";
    }
    throw std::invalid_argument("unknown dtype");
}

DType dtype_from_numpy_name(const std::string& name) {
    if (name == "uint8") return DType::U8;
    if (name == "uint16") return DType::U16;
    if (name == "uint32") return DType::U32;
    if (name == "uint64") return DType::U64;
    if (name == "int8") return DType::I8;
    if (name == "int16") return DType::I16;
    if (name == "int32") return DType::I32;
    if (name == "int64") return DType::I64;
    if (name == "float32") return DType::F32;
    if (name == "float64") return DType::F64;
    throw std::invalid_argument("unknown numpy name: " + name);
}

}  // namespace pclvideo
```

- [ ] **Step 5: Configure, build, and run the test**

Run:
```bash
cmake -S cpp_project -B cpp_project/build
cmake --build cpp_project/build
ctest --test-dir cpp_project/build --output-on-failure
```
Expected: `test_dtype` PASSES (1 test case).

- [ ] **Step 6: Commit**

```bash
git add cpp_project/CMakeLists.txt cpp_project/include cpp_project/src cpp_project/tests cpp_project/.gitignore
git commit -m "C++ skeleton: dtype unit + doctest harness"
```

### Task B2: NpyWriter

**Files:**
- Create: `cpp_project/include/pclvideo/npy_writer.hpp`
- Create: `cpp_project/src/pclvideo/npy_writer.cpp`
- Create: `cpp_project/tests/test_npy_writer.cpp`
- Modify: `cpp_project/CMakeLists.txt` (add source + test)

- [ ] **Step 1: Write the header**

Create `cpp_project/include/pclvideo/npy_writer.hpp`:

```cpp
#pragma once
#include <cstdint>
#include <filesystem>
#include <vector>
#include "pclvideo/dtype.hpp"

namespace pclvideo {

// Writes a NumPy .npy v1.0 file (little-endian, C-order).
void write_npy(const std::filesystem::path& path,
               const std::uint8_t* data,
               const std::vector<std::size_t>& shape,
               DType dtype);

}  // namespace pclvideo
```

- [ ] **Step 2: Write the failing test**

Create `cpp_project/tests/test_npy_writer.cpp`:

```cpp
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include <cstdint>
#include <fstream>
#include <vector>
#include "pclvideo/npy_writer.hpp"

using namespace pclvideo;

TEST_CASE("npy header is v1.0 and well-formed") {
    std::vector<std::uint32_t> data{1, 2, 3, 4, 5, 6};
    auto path = std::filesystem::temp_directory_path() / "t.npy";
    write_npy(path, reinterpret_cast<std::uint8_t*>(data.data()), {2, 3},
              DType::U32);

    std::ifstream f(path, std::ios::binary);
    std::vector<char> bytes((std::istreambuf_iterator<char>(f)), {});
    // magic
    CHECK(bytes[0] == '\x93');
    CHECK(std::string(bytes.begin() + 1, bytes.begin() + 6) == "NUMPY");
    CHECK(bytes[6] == 1);  // major version
    CHECK(bytes[7] == 0);  // minor version
    std::string s(bytes.begin(), bytes.end());
    CHECK(s.find("'descr': '<u4'") != std::string::npos);
    CHECK(s.find("'shape': (2, 3)") != std::string::npos);
    // total length is header + 6*4 data bytes, and divisible by 64
    std::uint16_t hlen = std::uint8_t(bytes[8]) | (std::uint8_t(bytes[9]) << 8);
    CHECK((10 + hlen) % 64 == 0);
    CHECK(bytes.size() == 10 + hlen + 6 * 4);
}
```

- [ ] **Step 3: Add to CMake and run to confirm failure**

Append to `cpp_project/CMakeLists.txt`: add `src/pclvideo/npy_writer.cpp` to the `pclvideo` library sources, and after the existing test:

```cmake
add_executable(test_npy_writer tests/test_npy_writer.cpp)
target_link_libraries(test_npy_writer PRIVATE pclvideo doctest::doctest)
add_test(NAME test_npy_writer COMMAND test_npy_writer)
```

Run: `cmake --build cpp_project/build` — Expected: link error (write_npy undefined) or, once stubbed, test FAIL.

- [ ] **Step 4: Implement `cpp_project/src/pclvideo/npy_writer.cpp`**

```cpp
#include "pclvideo/npy_writer.hpp"
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace pclvideo {

void write_npy(const std::filesystem::path& path, const std::uint8_t* data,
               const std::vector<std::size_t>& shape, DType dtype) {
    std::ostringstream shape_ss;
    shape_ss << "(";
    for (std::size_t i = 0; i < shape.size(); ++i) {
        shape_ss << shape[i];
        if (shape.size() == 1 || i + 1 < shape.size()) shape_ss << ", ";
    }
    shape_ss << ")";

    std::ostringstream hdr;
    hdr << "{'descr': '" << dtype_npy_descr(dtype)
        << "', 'fortran_order': False, 'shape': " << shape_ss.str() << ", }";
    std::string header = hdr.str();

    // Pad with spaces so that 10 + header_len is a multiple of 64, ending in \n.
    std::size_t base = 10 + header.size() + 1;  // +1 for trailing newline
    std::size_t pad = (64 - (base % 64)) % 64;
    header.append(pad, ' ');
    header.push_back('\n');

    std::uint16_t hlen = static_cast<std::uint16_t>(header.size());

    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("cannot open " + path.string());
    f.put('\x93');
    f.write("NUMPY", 5);
    f.put(1);  // major
    f.put(0);  // minor
    f.put(static_cast<char>(hlen & 0xff));
    f.put(static_cast<char>((hlen >> 8) & 0xff));
    f.write(header.data(), header.size());

    std::size_t count = 1;
    for (std::size_t d : shape) count *= d;
    f.write(reinterpret_cast<const char*>(data),
            static_cast<std::streamsize>(count * dtype_size(dtype)));
}

}  // namespace pclvideo
```

- [ ] **Step 5: Build and run the C++ test**

Run: `cmake --build cpp_project/build && ctest --test-dir cpp_project/build -R test_npy_writer --output-on-failure`
Expected: PASS.

- [ ] **Step 6: Cross-check that NumPy can load it**

Run:
```bash
uv run python - <<'PY'
import numpy as np, tempfile, subprocess, os
# write via the test binary's logic by invoking a tiny C++? Instead reuse the file the test wrote:
p = os.path.join(tempfile.gettempdir(), "t.npy")
a = np.load(p)
assert a.dtype == np.uint32 and a.shape == (2, 3)
assert a.tolist() == [[1, 2, 3], [4, 5, 6]]
print("npy loads in numpy OK", a.tolist())
PY
```
Expected: prints `npy loads in numpy OK [[1, 2, 3], [4, 5, 6]]`.

- [ ] **Step 7: Commit**

```bash
git add cpp_project/CMakeLists.txt cpp_project/include/pclvideo/npy_writer.hpp cpp_project/src/pclvideo/npy_writer.cpp cpp_project/tests/test_npy_writer.cpp
git commit -m "Add NpyWriter (numpy .npy v1.0 output)"
```

### Task B3: TarWriter (POSIX ustar)

**Files:**
- Create: `cpp_project/include/pclvideo/tar_writer.hpp`
- Create: `cpp_project/src/pclvideo/tar_writer.cpp`
- Create: `cpp_project/tests/test_tar_writer.cpp`
- Modify: `cpp_project/CMakeLists.txt`

- [ ] **Step 1: Write the header**

Create `cpp_project/include/pclvideo/tar_writer.hpp`:

```cpp
#pragma once
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace pclvideo {

// Minimal POSIX ustar writer. All members are regular files. Uncompressed,
// matching Python's tarfile.TarFile(mode="w").
class TarWriter {
public:
    explicit TarWriter(const std::filesystem::path& out_path);
    ~TarWriter();

    void add_bytes(const std::string& arcname, const std::uint8_t* data,
                   std::size_t size);
    void add_file(const std::string& arcname,
                  const std::filesystem::path& src);
    void close();

private:
    void write_header(const std::string& arcname, std::size_t size);
    std::ofstream out_;
    bool closed_ = false;
};

}  // namespace pclvideo
```

- [ ] **Step 2: Write the failing test**

Create `cpp_project/tests/test_tar_writer.cpp`:

```cpp
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include <filesystem>
#include "pclvideo/tar_writer.hpp"

using namespace pclvideo;

TEST_CASE("tar writes two members") {
    auto path = std::filesystem::temp_directory_path() / "out.tar";
    {
        TarWriter tw(path);
        std::string a = "hello";
        std::string b = "world!!";
        tw.add_bytes("a.txt", reinterpret_cast<const std::uint8_t*>(a.data()),
                     a.size());
        tw.add_bytes("dir/b.txt",
                     reinterpret_cast<const std::uint8_t*>(b.data()), b.size());
        tw.close();
    }
    // size must be a multiple of 512 (blocked archive)
    CHECK(std::filesystem::file_size(path) % 512 == 0);
}
```

- [ ] **Step 3: Add to CMake; build to confirm failure**

Append `src/pclvideo/tar_writer.cpp` to the `pclvideo` sources and add:

```cmake
add_executable(test_tar_writer tests/test_tar_writer.cpp)
target_link_libraries(test_tar_writer PRIVATE pclvideo doctest::doctest)
add_test(NAME test_tar_writer COMMAND test_tar_writer)
```

Run: `cmake --build cpp_project/build` — Expected: link error until implemented.

- [ ] **Step 4: Implement `cpp_project/src/pclvideo/tar_writer.cpp`**

```cpp
#include "pclvideo/tar_writer.hpp"
#include <cstring>
#include <stdexcept>

namespace pclvideo {
namespace {

void octal(char* field, std::size_t width, std::uint64_t value) {
    // width includes the trailing space/NUL terminator slot.
    std::memset(field, '0', width - 1);
    field[width - 1] = '\0';
    for (std::size_t i = width - 1; i-- > 0;) {
        field[i] = static_cast<char>('0' + (value & 7));
        value >>= 3;
    }
}

}  // namespace

TarWriter::TarWriter(const std::filesystem::path& out_path)
    : out_(out_path, std::ios::binary) {
    if (!out_) throw std::runtime_error("cannot open tar: " + out_path.string());
}

TarWriter::~TarWriter() {
    if (!closed_) {
        try { close(); } catch (...) {}
    }
}

void TarWriter::write_header(const std::string& arcname, std::size_t size) {
    if (arcname.size() > 100)
        throw std::runtime_error("arcname too long for ustar: " + arcname);

    char hdr[512];
    std::memset(hdr, 0, sizeof(hdr));
    std::memcpy(hdr, arcname.data(), arcname.size());      // name[100] @0
    octal(hdr + 100, 8, 0644);                             // mode[8] @100
    octal(hdr + 108, 8, 0);                                // uid[8] @108
    octal(hdr + 116, 8, 0);                                // gid[8] @116
    octal(hdr + 124, 12, size);                            // size[12] @124
    octal(hdr + 136, 12, 0);                               // mtime[12] @136
    std::memset(hdr + 148, ' ', 8);                        // chksum placeholder
    hdr[156] = '0';                                        // typeflag = regular
    std::memcpy(hdr + 257, "ustar", 5);                    // magic[6] @257
    hdr[263] = '0'; hdr[264] = '0';                        // version "00"

    unsigned chksum = 0;
    for (int i = 0; i < 512; ++i)
        chksum += static_cast<unsigned char>(hdr[i]);
    octal(hdr + 148, 7, chksum);                           // 6 digits + NUL
    hdr[155] = ' ';

    out_.write(hdr, 512);
}

void TarWriter::add_bytes(const std::string& arcname, const std::uint8_t* data,
                          std::size_t size) {
    write_header(arcname, size);
    out_.write(reinterpret_cast<const char*>(data),
               static_cast<std::streamsize>(size));
    std::size_t pad = (512 - (size % 512)) % 512;
    static const char zeros[512] = {0};
    if (pad) out_.write(zeros, static_cast<std::streamsize>(pad));
}

void TarWriter::add_file(const std::string& arcname,
                         const std::filesystem::path& src) {
    std::ifstream in(src, std::ios::binary);
    if (!in) throw std::runtime_error("cannot read " + src.string());
    std::vector<char> buf((std::istreambuf_iterator<char>(in)), {});
    add_bytes(arcname, reinterpret_cast<const std::uint8_t*>(buf.data()),
              buf.size());
}

void TarWriter::close() {
    if (closed_) return;
    static const char zeros[512] = {0};
    out_.write(zeros, 512);  // two zero blocks mark end-of-archive
    out_.write(zeros, 512);
    out_.flush();
    closed_ = true;
}

}  // namespace pclvideo
```

Add `#include <vector>` and `#include <iterator>` at the top if the compiler complains.

- [ ] **Step 5: Build and run the C++ test**

Run: `cmake --build cpp_project/build && ctest --test-dir cpp_project/build -R test_tar_writer --output-on-failure`
Expected: PASS.

- [ ] **Step 6: Cross-check that Python's tarfile reads it**

Run:
```bash
uv run python - <<'PY'
import tarfile, tempfile, os
p = os.path.join(tempfile.gettempdir(), "out.tar")
with tarfile.open(p) as tf:
    names = tf.getnames()
    assert names == ["a.txt", "dir/b.txt"], names
    assert tf.extractfile("a.txt").read() == b"hello"
    assert tf.extractfile("dir/b.txt").read() == b"world!!"
print("tar reads in python OK", names)
PY
```
Expected: `tar reads in python OK ['a.txt', 'dir/b.txt']`.

- [ ] **Step 7: Commit**

```bash
git add cpp_project/CMakeLists.txt cpp_project/include/pclvideo/tar_writer.hpp cpp_project/src/pclvideo/tar_writer.cpp cpp_project/tests/test_tar_writer.cpp
git commit -m "Add ustar TarWriter readable by python tarfile"
```

### Task B4: YamlMetaWriter

**Files:**
- Create: `cpp_project/include/pclvideo/yaml_meta_writer.hpp`
- Create: `cpp_project/src/pclvideo/yaml_meta_writer.cpp`
- Create: `cpp_project/tests/test_yaml_meta_writer.cpp`
- Modify: `cpp_project/CMakeLists.txt`

- [ ] **Step 1: Write the header**

Create `cpp_project/include/pclvideo/yaml_meta_writer.hpp`:

```cpp
#pragma once
#include <map>
#include <string>
#include <utility>
#include <vector>
#include "pclvideo/dtype.hpp"

namespace pclvideo {

struct FieldTypeMeta {
    std::string name;
    DType element_type;
    std::vector<int> extra_dims;
    int field_class;
};

// Emits the fixed metadata schema matching main.py's YAML. Returns the document
// as a string (so it can be added to the tar without a temp file).
std::string emit_metadata_yaml(
    int num_scans,
    const std::vector<FieldTypeMeta>& field_types,
    const std::map<std::string, std::vector<std::pair<int, DType>>>&
        fields_to_channels);

}  // namespace pclvideo
```

- [ ] **Step 2: Write the failing test**

Create `cpp_project/tests/test_yaml_meta_writer.cpp`:

```cpp
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include "pclvideo/yaml_meta_writer.hpp"

using namespace pclvideo;

TEST_CASE("yaml metadata contains expected keys and values") {
    std::vector<FieldTypeMeta> fts{
        {"RANGE", DType::U32, {}, 1},
    };
    std::map<std::string, std::vector<std::pair<int, DType>>> ftc{
        {"RANGE", {{0, DType::U32}, {1, DType::U32}}},
        {"pose", {{0, DType::F64}}},
    };
    std::string doc = emit_metadata_yaml(7, fts, ftc);
    CHECK(doc.find("num_scans: 7") != std::string::npos);
    CHECK(doc.find("name: RANGE") != std::string::npos);
    CHECK(doc.find("element_type: uint32") != std::string::npos);
    CHECK(doc.find("field_class: 1") != std::string::npos);
    CHECK(doc.find("pose:") != std::string::npos);
    CHECK(doc.find("- [0, float64]") != std::string::npos);
}
```

- [ ] **Step 3: Add to CMake; build to confirm failure**

Append `src/pclvideo/yaml_meta_writer.cpp` to the library and add the matching `add_executable`/`add_test` lines (named `test_yaml_meta_writer`). Run `cmake --build cpp_project/build` — Expected: link error until implemented.

- [ ] **Step 4: Implement `cpp_project/src/pclvideo/yaml_meta_writer.cpp`**

```cpp
#include "pclvideo/yaml_meta_writer.hpp"
#include <sstream>

namespace pclvideo {

std::string emit_metadata_yaml(
    int num_scans, const std::vector<FieldTypeMeta>& field_types,
    const std::map<std::string, std::vector<std::pair<int, DType>>>&
        fields_to_channels) {
    std::ostringstream o;
    o << "num_scans: " << num_scans << "\n";

    o << "field_types:\n";
    for (const auto& ft : field_types) {
        o << "- name: " << ft.name << "\n";
        o << "  element_type: " << dtype_numpy_name(ft.element_type) << "\n";
        o << "  extra_dims: [";
        for (std::size_t i = 0; i < ft.extra_dims.size(); ++i) {
            o << ft.extra_dims[i];
            if (i + 1 < ft.extra_dims.size()) o << ", ";
        }
        o << "]\n";
        o << "  field_class: " << ft.field_class << "\n";
    }

    o << "fields_to_channels:\n";
    for (const auto& [field, channels] : fields_to_channels) {
        o << "  " << field << ":\n";
        for (const auto& [ch, dt] : channels) {
            o << "  - [" << ch << ", " << dtype_numpy_name(dt) << "]\n";
        }
    }
    return o.str();
}

}  // namespace pclvideo
```

- [ ] **Step 5: Build and run the C++ test**

Run: `cmake --build cpp_project/build && ctest --test-dir cpp_project/build -R test_yaml_meta_writer --output-on-failure`
Expected: PASS.

- [ ] **Step 6: Cross-check that PyYAML parses it into the expected structure**

Run:
```bash
uv run python - <<'PY'
import yaml
doc = """num_scans: 7
field_types:
- name: RANGE
  element_type: uint32
  extra_dims: []
  field_class: 1
fields_to_channels:
  RANGE:
  - [0, uint32]
  - [1, uint32]
  pose:
  - [0, float64]
"""
d = yaml.safe_load(doc)
assert d["num_scans"] == 7
assert d["field_types"][0]["element_type"] == "uint32"
assert d["fields_to_channels"]["pose"] == [[0, "float64"]]
print("pyyaml parses metadata OK")
PY
```
Expected: `pyyaml parses metadata OK`.

- [ ] **Step 7: Commit**

```bash
git add cpp_project/CMakeLists.txt cpp_project/include/pclvideo/yaml_meta_writer.hpp cpp_project/src/pclvideo/yaml_meta_writer.cpp cpp_project/tests/test_yaml_meta_writer.cpp
git commit -m "Add YamlMetaWriter matching main.py schema"
```

### Task B5: ChannelEncoder (libavcodec gray → H.265)

**Files:**
- Create: `cpp_project/include/pclvideo/channel_encoder.hpp`
- Create: `cpp_project/src/pclvideo/channel_encoder.cpp`
- Create: `cpp_project/tests/test_channel_encoder.cpp`
- Modify: `cpp_project/CMakeLists.txt` (locate libav, link it)

- [ ] **Step 1: Make CMake find libav**

Append to `cpp_project/CMakeLists.txt` (after the `project()` block):

```cmake
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET
  libavcodec libavformat libavutil)
```

And link the core library to it: change the `pclvideo` target to
`target_link_libraries(pclvideo PUBLIC PkgConfig::LIBAV)`.

- [ ] **Step 2: Write the header**

Create `cpp_project/include/pclvideo/channel_encoder.hpp`:

```cpp
#pragma once
#include <cstdint>
#include <filesystem>
#include <optional>

struct AVFormatContext;
struct AVCodecContext;
struct AVStream;
struct AVFrame;
struct AVPacket;

namespace pclvideo {

// Encodes a sequence of single-channel gray8 frames to one H.265 .mp4 using
// libavcodec/libx265. qp_level 0 => lossless.
class ChannelEncoder {
public:
    ChannelEncoder(const std::filesystem::path& out_path, int width,
                   int height, double frame_rate, int qp_level,
                   std::optional<int> gop_size);
    ~ChannelEncoder();
    ChannelEncoder(const ChannelEncoder&) = delete;
    ChannelEncoder& operator=(const ChannelEncoder&) = delete;

    // data points to width*height gray8 bytes (row-major).
    void write_frame(const std::uint8_t* data);
    void close();  // flush + write trailer; idempotent

private:
    void drain(AVFrame* frame);

    AVFormatContext* fmt_ = nullptr;
    AVCodecContext* cctx_ = nullptr;
    AVStream* stream_ = nullptr;
    AVFrame* frame_ = nullptr;
    AVPacket* pkt_ = nullptr;
    int width_, height_;
    std::int64_t pts_ = 0;
    bool closed_ = false;
};

}  // namespace pclvideo
```

- [ ] **Step 3: Write the failing test (encode then decode, assert lossless)**

Create `cpp_project/tests/test_channel_encoder.cpp`:

```cpp
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include <cstdint>
#include <filesystem>
#include <vector>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
}
#include "pclvideo/channel_encoder.hpp"

using namespace pclvideo;

// Decode all gray8 frames from an mp4 into a flat per-frame byte vector.
static std::vector<std::vector<std::uint8_t>> decode_gray(
    const std::filesystem::path& p, int w, int h) {
    AVFormatContext* fmt = nullptr;
    REQUIRE(avformat_open_input(&fmt, p.string().c_str(), nullptr, nullptr) == 0);
    avformat_find_stream_info(fmt, nullptr);
    int vs = av_find_best_stream(fmt, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
    const AVCodec* dec = avcodec_find_decoder(fmt->streams[vs]->codecpar->codec_id);
    AVCodecContext* c = avcodec_alloc_context3(dec);
    avcodec_parameters_to_context(c, fmt->streams[vs]->codecpar);
    avcodec_open2(c, dec, nullptr);
    AVPacket* pkt = av_packet_alloc();
    AVFrame* fr = av_frame_alloc();
    std::vector<std::vector<std::uint8_t>> out;
    auto pull = [&]() {
        while (avcodec_receive_frame(c, fr) == 0) {
            std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) * h);
            for (int y = 0; y < h; ++y)
                std::copy(fr->data[0] + y * fr->linesize[0],
                          fr->data[0] + y * fr->linesize[0] + w,
                          buf.data() + static_cast<std::size_t>(y) * w);
            out.push_back(std::move(buf));
        }
    };
    while (av_read_frame(fmt, pkt) == 0) {
        if (pkt->stream_index == vs) { avcodec_send_packet(c, pkt); pull(); }
        av_packet_unref(pkt);
    }
    avcodec_send_packet(c, nullptr);
    pull();
    av_frame_free(&fr); av_packet_free(&pkt);
    avcodec_free_context(&c); avformat_close_input(&fmt);
    return out;
}

TEST_CASE("lossless gray encode round-trips byte-exact") {
    const int W = 128, H = 64, N = 8;
    std::vector<std::vector<std::uint8_t>> frames;
    for (int i = 0; i < N; ++i) {
        std::vector<std::uint8_t> f(static_cast<std::size_t>(W) * H);
        for (std::size_t k = 0; k < f.size(); ++k)
            f[k] = static_cast<std::uint8_t>((k * 7 + i * 13) & 0xff);
        frames.push_back(std::move(f));
    }
    auto path = std::filesystem::temp_directory_path() / "enc.mp4";
    {
        ChannelEncoder enc(path, W, H, 10.0, /*qp=*/0, std::nullopt);
        for (auto& f : frames) enc.write_frame(f.data());
        enc.close();
    }
    auto decoded = decode_gray(path, W, H);
    REQUIRE(decoded.size() == static_cast<std::size_t>(N));
    for (int i = 0; i < N; ++i) CHECK(decoded[i] == frames[i]);
}
```

- [ ] **Step 4: Add to CMake; build to confirm failure**

Add `src/pclvideo/channel_encoder.cpp` to the library and:

```cmake
add_executable(test_channel_encoder tests/test_channel_encoder.cpp)
target_link_libraries(test_channel_encoder PRIVATE pclvideo doctest::doctest PkgConfig::LIBAV)
add_test(NAME test_channel_encoder COMMAND test_channel_encoder)
```

Run `cmake --build cpp_project/build` — Expected: link error until implemented.

- [ ] **Step 5: Implement `cpp_project/src/pclvideo/channel_encoder.cpp`**

```cpp
#include "pclvideo/channel_encoder.hpp"
#include <stdexcept>
#include <string>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libavutil/opt.h>
}

namespace pclvideo {
namespace {
void check(int ret, const char* what) {
    if (ret < 0) {
        char buf[256];
        av_strerror(ret, buf, sizeof(buf));
        throw std::runtime_error(std::string(what) + ": " + buf);
    }
}
}  // namespace

ChannelEncoder::ChannelEncoder(const std::filesystem::path& out_path, int width,
                               int height, double frame_rate, int qp_level,
                               std::optional<int> gop_size)
    : width_(width), height_(height) {
    check(avformat_alloc_output_context2(&fmt_, nullptr, nullptr,
                                         out_path.string().c_str()),
          "alloc output ctx");

    const AVCodec* codec = avcodec_find_encoder_by_name("libx265");
    if (!codec) throw std::runtime_error("libx265 encoder not available");

    stream_ = avformat_new_stream(fmt_, nullptr);
    cctx_ = avcodec_alloc_context3(codec);
    cctx_->width = width;
    cctx_->height = height;
    cctx_->pix_fmt = AV_PIX_FMT_GRAY8;
    // time_base 1/1000; pts in ms keeps a stable nominal frame rate.
    cctx_->time_base = AVRational{1, 1000};
    cctx_->framerate = av_d2q(frame_rate, 100000);
    if (gop_size) cctx_->gop_size = *gop_size;
    if (fmt_->oformat->flags & AVFMT_GLOBALHEADER)
        cctx_->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;

    av_opt_set(cctx_->priv_data, "preset", "ultrafast", 0);
    av_opt_set_int(cctx_->priv_data, "qp", qp_level, 0);
    std::string x265;
    if (qp_level == 0) x265 = "lossless=1";
    if (gop_size) x265 += (x265.empty() ? "" : ":") + ("keyint=" + std::to_string(*gop_size));
    if (!x265.empty()) av_opt_set(cctx_->priv_data, "x265-params", x265.c_str(), 0);

    check(avcodec_open2(cctx_, codec, nullptr), "open encoder");
    check(avcodec_parameters_from_context(stream_->codecpar, cctx_),
          "params from ctx");
    stream_->time_base = cctx_->time_base;

    if (!(fmt_->oformat->flags & AVFMT_NOFILE))
        check(avio_open(&fmt_->pb, out_path.string().c_str(), AVIO_FLAG_WRITE),
              "avio_open");
    check(avformat_write_header(fmt_, nullptr), "write header");

    frame_ = av_frame_alloc();
    frame_->format = AV_PIX_FMT_GRAY8;
    frame_->width = width;
    frame_->height = height;
    check(av_frame_get_buffer(frame_, 0), "frame buffer");
    pkt_ = av_packet_alloc();
}

void ChannelEncoder::drain(AVFrame* frame) {
    check(avcodec_send_frame(cctx_, frame), "send_frame");
    for (;;) {
        int ret = avcodec_receive_packet(cctx_, pkt_);
        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
        check(ret, "receive_packet");
        av_packet_rescale_ts(pkt_, cctx_->time_base, stream_->time_base);
        pkt_->stream_index = stream_->index;
        check(av_interleaved_write_frame(fmt_, pkt_), "write_frame");
        av_packet_unref(pkt_);
    }
}

void ChannelEncoder::write_frame(const std::uint8_t* data) {
    check(av_frame_make_writable(frame_), "make_writable");
    for (int y = 0; y < height_; ++y)
        std::copy(data + static_cast<std::size_t>(y) * width_,
                  data + static_cast<std::size_t>(y) * width_ + width_,
                  frame_->data[0] + y * frame_->linesize[0]);
    // pts in ms from a stable nominal frame rate
    frame_->pts = av_rescale_q(pts_++, AVRational{1, 1},
                               AVRational{cctx_->framerate.den,
                                          cctx_->framerate.num});
    drain(frame_);
}

void ChannelEncoder::close() {
    if (closed_) return;
    closed_ = true;
    drain(nullptr);  // flush
    av_write_trailer(fmt_);
    if (fmt_ && !(fmt_->oformat->flags & AVFMT_NOFILE)) avio_closep(&fmt_->pb);
}

ChannelEncoder::~ChannelEncoder() {
    try { close(); } catch (...) {}
    av_frame_free(&frame_);
    av_packet_free(&pkt_);
    avcodec_free_context(&cctx_);
    avformat_free_context(fmt_);
}

}  // namespace pclvideo
```

- [ ] **Step 6: Build and run the encoder test**

Run: `cmake --build cpp_project/build && ctest --test-dir cpp_project/build -R test_channel_encoder --output-on-failure`
Expected: PASS (`decoded[i] == frames[i]` for all frames — lossless byte-exact).

- [ ] **Step 7: Commit**

```bash
git add cpp_project/CMakeLists.txt cpp_project/include/pclvideo/channel_encoder.hpp cpp_project/src/pclvideo/channel_encoder.cpp cpp_project/tests/test_channel_encoder.cpp
git commit -m "Add ChannelEncoder (libavcodec gray H.265, lossless verified)"
```

### Task B6: TarVideoWriter (orchestration: byte-split + bundle)

**Files:**
- Create: `cpp_project/include/pclvideo/tar_video_writer.hpp`
- Create: `cpp_project/src/pclvideo/tar_video_writer.cpp`
- Create: `cpp_project/tests/test_tar_video_writer.cpp`
- Modify: `cpp_project/CMakeLists.txt`

- [ ] **Step 1: Write the header**

Create `cpp_project/include/pclvideo/tar_video_writer.hpp`:

```cpp
#pragma once
#include <cstdint>
#include <filesystem>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include "pclvideo/channel_encoder.hpp"
#include "pclvideo/dtype.hpp"
#include "pclvideo/yaml_meta_writer.hpp"

namespace pclvideo {

struct FieldView {
    std::string name;
    const std::uint8_t* data;  // row-major, height*width*dtype_size bytes
    int height;
    int width;
    DType dtype;
};

struct AuxArray {
    std::string name;
    const std::uint8_t* data;
    std::vector<std::size_t> shape;
    DType dtype;
};

class TarVideoWriter {
public:
    TarVideoWriter(std::filesystem::path out_path,
                   std::filesystem::path work_dir, int qp_level,
                   std::optional<int> gop_size, double frame_rate,
                   std::filesystem::path sensor_json_path,
                   std::vector<FieldTypeMeta> field_types);

    void add_scan(const std::vector<FieldView>& fields,
                  const std::vector<AuxArray>& aux, std::uint64_t packet_ts);
    void finalize();

private:
    std::filesystem::path out_path_, work_dir_, sensor_json_path_;
    int qp_level_;
    std::optional<int> gop_size_;
    double frame_rate_;
    std::vector<FieldTypeMeta> field_types_;
    int num_scans_ = 0;

    std::map<std::pair<std::string, int>, std::unique_ptr<ChannelEncoder>> enc_;
    std::map<std::string, std::vector<std::pair<int, DType>>> ftc_;

    void stream_field(const FieldView& f);
};

}  // namespace pclvideo
```

- [ ] **Step 2: Write the failing integration test**

Create `cpp_project/tests/test_tar_video_writer.cpp`:

```cpp
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include <cstdint>
#include <filesystem>
#include <vector>
#include "pclvideo/tar_video_writer.hpp"

using namespace pclvideo;

TEST_CASE("writes a tar with the expected members from synthetic scans") {
    const int W = 32, H = 16, N = 4;
    auto work = std::filesystem::temp_directory_path() / "tvw_work";
    std::filesystem::remove_all(work);
    auto out = std::filesystem::temp_directory_path() / "tvw.tar";
    // minimal sensor json
    auto json = std::filesystem::temp_directory_path() / "tvw.json";
    { std::ofstream(json) << "{}"; }

    std::vector<FieldTypeMeta> fts{{"RANGE", DType::U32, {}, 1}};
    TarVideoWriter w(out, work, /*qp=*/0, std::nullopt, 10.0, json, fts);

    std::vector<std::uint32_t> range(static_cast<std::size_t>(W) * H);
    for (int s = 0; s < N; ++s) {
        for (std::size_t k = 0; k < range.size(); ++k)
            range[k] = static_cast<std::uint32_t>(k + s);
        FieldView fv{"RANGE",
                     reinterpret_cast<std::uint8_t*>(range.data()), H, W,
                     DType::U32};
        std::vector<std::uint64_t> ts{static_cast<std::uint64_t>(s)};
        AuxArray aux{"timestamp", reinterpret_cast<std::uint8_t*>(ts.data()),
                     {1}, DType::U64};
        w.add_scan({fv}, {aux}, static_cast<std::uint64_t>(1000 + s));
    }
    w.finalize();
    CHECK(std::filesystem::exists(out));
    CHECK(std::filesystem::file_size(out) % 512 == 0);
}
```

Add `#include <fstream>` at the top of the test.

- [ ] **Step 3: Add to CMake; build to confirm failure**

Add `src/pclvideo/tar_video_writer.cpp` to the library and a `test_tar_video_writer` executable/test (link `pclvideo doctest::doctest PkgConfig::LIBAV`). Run `cmake --build cpp_project/build` — Expected: link error until implemented.

- [ ] **Step 4: Implement `cpp_project/src/pclvideo/tar_video_writer.cpp`**

```cpp
#include "pclvideo/tar_video_writer.hpp"
#include <fstream>
#include <stdexcept>
#include "pclvideo/npy_writer.hpp"
#include "pclvideo/tar_writer.hpp"

namespace pclvideo {

TarVideoWriter::TarVideoWriter(std::filesystem::path out_path,
                               std::filesystem::path work_dir, int qp_level,
                               std::optional<int> gop_size, double frame_rate,
                               std::filesystem::path sensor_json_path,
                               std::vector<FieldTypeMeta> field_types)
    : out_path_(std::move(out_path)),
      work_dir_(std::move(work_dir)),
      sensor_json_path_(std::move(sensor_json_path)),
      qp_level_(qp_level),
      gop_size_(gop_size),
      frame_rate_(frame_rate),
      field_types_(std::move(field_types)) {
    std::filesystem::create_directories(work_dir_);
    if (!std::filesystem::is_empty(work_dir_))
        throw std::runtime_error("work dir is not empty: " + work_dir_.string());
}

void TarVideoWriter::stream_field(const FieldView& f) {
    const std::size_t esz = dtype_size(f.dtype);
    const std::size_t npix = static_cast<std::size_t>(f.height) * f.width;
    std::vector<std::uint8_t> chan(npix);
    for (std::size_t c = 0; c < esz; ++c) {
        for (std::size_t p = 0; p < npix; ++p)
            chan[p] = f.data[p * esz + c];  // little-endian byte split
        auto key = std::make_pair(f.name, static_cast<int>(c));
        auto it = enc_.find(key);
        if (it == enc_.end()) {
            auto path = work_dir_ / (f.name + "_ch" + std::to_string(c) + ".mp4");
            enc_.emplace(key, std::make_unique<ChannelEncoder>(
                                  path, f.width, f.height, frame_rate_,
                                  qp_level_, gop_size_));
            ftc_[f.name].emplace_back(static_cast<int>(c), f.dtype);
        }
        enc_.at(key)->write_frame(chan.data());
    }
}

void TarVideoWriter::add_scan(const std::vector<FieldView>& fields,
                              const std::vector<AuxArray>& aux,
                              std::uint64_t packet_ts) {
    ++num_scans_;
    for (const auto& f : fields) stream_field(f);
    for (const auto& a : aux) {
        auto dir = work_dir_ / a.name;
        std::filesystem::create_directories(dir);
        write_npy(dir / (std::to_string(packet_ts) + ".npy"), a.data, a.shape,
                  a.dtype);
    }
}

void TarVideoWriter::finalize() {
    for (auto& [key, enc] : enc_) enc->close();

    TarWriter tw(out_path_);
    for (auto& entry : std::filesystem::directory_iterator(work_dir_)) {
        if (entry.is_regular_file() && entry.path().extension() == ".mp4")
            tw.add_file(entry.path().filename().string(), entry.path());
    }
    tw.add_file("metadata.json", sensor_json_path_);
    for (auto& entry :
         std::filesystem::recursive_directory_iterator(work_dir_)) {
        if (entry.is_regular_file() && entry.path().extension() == ".npy") {
            auto rel = std::filesystem::relative(entry.path(), work_dir_);
            tw.add_file(rel.generic_string(), entry.path());
        }
    }
    std::string yaml = emit_metadata_yaml(num_scans_, field_types_, ftc_);
    tw.add_bytes("_pcl_video_metadata.yaml",
                 reinterpret_cast<const std::uint8_t*>(yaml.data()),
                 yaml.size());
    tw.close();
}

}  // namespace pclvideo
```

- [ ] **Step 5: Build and run the test**

Run: `cmake --build cpp_project/build && ctest --test-dir cpp_project/build -R test_tar_video_writer --output-on-failure`
Expected: PASS.

- [ ] **Step 6: Cross-check that the synthetic tar reconstructs in Python**

Run:
```bash
uv run python - <<'PY'
import tarfile, tempfile, os, yaml
p = os.path.join(tempfile.gettempdir(), "tvw.tar")
with tarfile.open(p) as tf:
    names = set(tf.getnames())
    assert "_pcl_video_metadata.yaml" in names
    assert "metadata.json" in names
    assert any(n.endswith("RANGE_ch0.mp4") for n in names), names
    meta = yaml.safe_load(tf.extractfile("_pcl_video_metadata.yaml"))
    assert meta["num_scans"] == 4, meta
    assert len(meta["fields_to_channels"]["RANGE"]) == 4
print("synthetic C++ tar OK", sorted(names))
PY
```
Expected: prints the member list with four `RANGE_ch*.mp4`, `metadata.json`, `_pcl_video_metadata.yaml`, and four `timestamp/*.npy`.

- [ ] **Step 7: Commit**

```bash
git add cpp_project/CMakeLists.txt cpp_project/include/pclvideo/tar_video_writer.hpp cpp_project/src/pclvideo/tar_video_writer.cpp cpp_project/tests/test_tar_video_writer.cpp
git commit -m "Add TarVideoWriter: byte-split, encode, bundle to tar"
```

---

## Phase C — pcap CLI front-end `pcl2tar`

### Task C1: FetchContent ouster-sdk + CLI target stub

**Files:**
- Modify: `cpp_project/CMakeLists.txt`
- Create: `cpp_project/src/cli/main.cpp`

- [ ] **Step 1: Add ouster-sdk via FetchContent and a CLI target**

Append to `cpp_project/CMakeLists.txt`:

```cmake
FetchContent_Declare(
  ouster_sdk
  GIT_REPOSITORY https://github.com/ouster-lidar/ouster-sdk.git
  GIT_TAG 20240702  # pin to a release tag matching the Python ouster-sdk major
)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(BUILD_VIZ OFF CACHE BOOL "" FORCE)
set(BUILD_PCAP ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(ouster_sdk)

add_executable(pcl2tar src/cli/main.cpp)
target_link_libraries(pcl2tar PRIVATE pclvideo OusterSDK::ouster_client OusterSDK::ouster_pcap)
```

(If the exported target names differ for the pinned tag, run `cmake --build` and read the error; ouster-sdk exports `OusterSDK::ouster_client` / `OusterSDK::ouster_pcap` in recent releases.)

- [ ] **Step 2: Write a minimal CLI that parses args and opens the pcap**

Create `cpp_project/src/cli/main.cpp`:

```cpp
#include <iostream>
#include <optional>
#include <string>
#include <ouster/os_pcap.h>
#include <ouster/lidar_scan.h>
#include <ouster/types.h>

int main(int argc, char** argv) {
    std::string pcap, json;
    int qp = 0;
    std::optional<int> gop;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() { return std::string(argv[++i]); };
        if (a == "-i" || a == "--input") pcap = next();
        else if (a == "-j" || a == "--json-input") json = next();
        else if (a == "--qp") qp = std::stoi(next());
        else if (a == "--gop-size") gop = std::stoi(next());
    }
    if (pcap.empty()) { std::cerr << "missing -i <pcap>\n"; return 2; }
    if (json.empty()) json = pcap.substr(0, pcap.rfind('.')) + ".json";

    auto info = ouster::sensor::metadata_from_json(json);
    std::cout << "opened sensor: " << info.prod_line
              << " mode=" << ouster::sensor::to_string(info.config.lidar_mode)
              << "\n";
    return 0;
}
```

- [ ] **Step 3: Configure and build (first ouster-sdk build is slow)**

Run:
```bash
cmake -S cpp_project -B cpp_project/build
cmake --build cpp_project/build --target pcl2tar
```
Expected: `pcl2tar` builds. If target names or headers differ for the pinned tag, fix per the compiler/CMake error and re-run.

- [ ] **Step 4: Smoke-run the CLI**

Run:
```bash
./cpp_project/build/pcl2tar -i data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap
```
Expected: prints `opened sensor: ... mode=2048x10`.

- [ ] **Step 5: Commit**

```bash
git add cpp_project/CMakeLists.txt cpp_project/src/cli/main.cpp
git commit -m "Add pcl2tar CLI stub with ouster-sdk via FetchContent"
```

### Task C2: CLI reads scans and drives TarVideoWriter

**Files:**
- Modify: `cpp_project/src/cli/main.cpp`

- [ ] **Step 1: Map Ouster types to pclvideo DType**

Add this helper near the top of `main.cpp`:

```cpp
#include "pclvideo/tar_video_writer.hpp"

static pclvideo::DType to_dtype(ouster::sensor::ChanFieldType t) {
    using CFT = ouster::sensor::ChanFieldType;
    switch (t) {
        case CFT::UINT8: return pclvideo::DType::U8;
        case CFT::UINT16: return pclvideo::DType::U16;
        case CFT::UINT32: return pclvideo::DType::U32;
        case CFT::UINT64: return pclvideo::DType::U64;
        default: throw std::runtime_error("unsupported chan field type");
    }
}
```

- [ ] **Step 2: Derive nominal frame rate from lidar mode**

Add:

```cpp
static double frame_rate_from_mode(ouster::sensor::lidar_mode m) {
    // e.g. MODE_2048x10 -> 10.0
    std::string s = ouster::sensor::to_string(m);  // "2048x10"
    auto x = s.rfind('x');
    return x == std::string::npos ? 10.0 : std::stod(s.substr(x + 1));
}
```

- [ ] **Step 3: Build field-type metadata and iterate scans**

Replace the body after loading `info` with the conversion loop:

```cpp
    using namespace ouster;
    sensor::sensor_info si = info;
    auto pf = sensor::get_format(si);

    std::vector<pclvideo::FieldTypeMeta> field_types;
    for (const auto& ft : si.get_field_types()) {
        field_types.push_back({ft.name, to_dtype(ft.element_type), {},
                                static_cast<int>(ft.field_class)});
    }

    auto handle = sensor_utils::replay_initialize(pcap);
    LidarScan scan(si);
    ScanBatcher batch(si);

    std::filesystem::path out = std::filesystem::path(pcap).replace_extension(".tar");
    std::filesystem::path work = std::filesystem::temp_directory_path() /
                                 ("pcl2tar_" + std::to_string(::getpid()));
    pclvideo::TarVideoWriter writer(out, work, qp, gop,
                                    frame_rate_from_mode(si.config.lidar_mode),
                                    json, field_types);

    sensor_utils::packet_info pi;
    LidarPacket pkt(pf.lidar_packet_size);
    while (sensor_utils::next_packet_info(*handle, pi)) {
        if (pi.dst_port != si.config.udp_port_lidar) continue;
        sensor_utils::read_packet(*handle, pkt);
        if (!batch(pkt, scan)) continue;  // scan not yet complete

        std::uint64_t ts = scan.packet_timestamp()[0];
        if (ts == 0) continue;

        std::vector<pclvideo::FieldView> fields;
        for (const auto& ft : si.get_field_types()) {
            auto f = scan.field<void>(ft.name);  // see note below
            fields.push_back({ft.name,
                              reinterpret_cast<const std::uint8_t*>(scan.field(ft.name).get_data()),
                              scan.h, scan.w, to_dtype(ft.element_type)});
        }
        // pose: row-major (w, 16) doubles
        pclvideo::FieldView pose{"pose",
            reinterpret_cast<const std::uint8_t*>(scan.pose().data()),
            static_cast<int>(scan.w), 16, pclvideo::DType::F64};
        fields.push_back(pose);

        // aux arrays
        std::vector<pclvideo::AuxArray> aux;
        auto add_aux = [&](const std::string& n, const std::uint8_t* d,
                           std::vector<std::size_t> shp, pclvideo::DType dt) {
            aux.push_back({n, d, std::move(shp), dt});
        };
        add_aux("timestamp",
                reinterpret_cast<const std::uint8_t*>(scan.timestamp().data()),
                {static_cast<std::size_t>(scan.timestamp().size())},
                pclvideo::DType::U64);
        add_aux("packet_timestamp",
                reinterpret_cast<const std::uint8_t*>(scan.packet_timestamp().data()),
                {static_cast<std::size_t>(scan.packet_timestamp().size())},
                pclvideo::DType::U64);
        add_aux("status",
                reinterpret_cast<const std::uint8_t*>(scan.status().data()),
                {static_cast<std::size_t>(scan.status().size())},
                pclvideo::DType::U32);

        writer.add_scan(fields, aux, ts);
    }
    writer.finalize();
    std::cout << "wrote " << out << "\n";
    return 0;
```

> **Note on field access:** the exact accessor for raw field bytes depends on the pinned ouster-sdk version. For recent releases, `scan.field(name)` returns an `ouster::img_t`/`Eigen` view; obtain the contiguous pointer (`.data()`), confirm it is row-major `h*w` of `element_type`. If the field is stored column-major, transpose into a scratch buffer before constructing the `FieldView` so the byte layout matches `main.py` (which uses the SDK's numpy `field(name)`, row-major `h*w`). Validate against the Python output in Task C3 and adjust this access if the equivalence test fails. `alert_flags` is included if present in `si.get_field_types()`; the four aux fields mirror `main.py`'s `AUX_FIELDS`.

- [ ] **Step 4: Build**

Run: `cmake --build cpp_project/build --target pcl2tar`
Expected: builds. Fix any accessor/signature mismatches against the pinned SDK per compiler errors.

- [ ] **Step 5: Commit**

```bash
git add cpp_project/src/cli/main.cpp
git commit -m "pcl2tar: read pcap scans and drive TarVideoWriter"
```

### Task C3: End-to-end equivalence vs `main.py`

**Files:**
- Create: `cpp_project/tests/equivalence_check.py`

- [ ] **Step 1: Write the equivalence script**

Create `cpp_project/tests/equivalence_check.py`:

```python
"""Compare the C++ pcl2tar output against main.py on the first N scans."""
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import av
import numpy as np
import ouster.sdk.pcap

import main  # noqa: E402

N = 8
PCAP = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241-000.pcap")
JSON = Path("data/OS-0-128_v3.0.1_2048x10_20230216_173241.json")
CPP = Path("cpp_project/build/pcl2tar")

_real = ouster.sdk.pcap.pcap_scan_source.PcapScanSource


class _Lim:
    def __init__(self, inner): self._i = inner
    def __iter__(self):
        it = iter(self._i)
        for _ in range(N):
            yield next(it)
    @property
    def scans_num(self): return N
    def __getattr__(self, n): return getattr(self._i, n)


class _Ctor:
    def __init__(self, *a, **k): self._s = _real(*a, **k)
    def single_source(self, i): return _Lim(self._s.single_source(i))


def decode_all(tf, name):
    with tempfile.TemporaryDirectory() as d:
        tf.extract(name, d)
        c = av.open(str(Path(d) / name))
        frames = np.stack([f.to_ndarray(channel_last=True) for f in c.decode(0)])
        c.close()
    return frames


def main_check():
    main.ouster.sdk.pcap.pcap_scan_source.PcapScanSource = _Ctor
    py_tar = Path(tempfile.mktemp(suffix=".tar"))
    main.create_tar_from_pcap(pcap_file=PCAP, output_file_path=py_tar,
                              json_path=JSON, qp_level=0)

    # The C++ side has no scan limit; it converts the whole pcap. For the
    # equivalence check we only compare the first N decoded frames of each video.
    cpp_tar = PCAP.with_suffix(".tar")
    subprocess.run([str(CPP), "-i", str(PCAP), "-j", str(JSON), "--qp", "0"],
                   check=True)

    ok = True
    with tarfile.open(py_tar) as tp, tarfile.open(cpp_tar) as tc:
        names_p = {n for n in tp.getnames() if n.endswith(".mp4")}
        names_c = {n for n in tc.getnames() if n.endswith(".mp4")}
        if names_p != names_c:
            print("MEMBER MISMATCH", names_p ^ names_c)
            ok = False
        for name in sorted(names_p & names_c):
            a = decode_all(tp, name)[:N]
            b = decode_all(tc, name)[:N]
            if not np.array_equal(a, b):
                print("VIDEO MISMATCH", name, a.shape, b.shape)
                ok = False
    print("EQUIVALENT (first %d frames)" % N if ok else "DIFFERENCES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_check())
```

- [ ] **Step 2: Run the equivalence check**

Run: `uv run python cpp_project/tests/equivalence_check.py`
Expected: prints `EQUIVALENT (first 8 frames)`.

If it reports a VIDEO MISMATCH, the most likely cause is field memory layout (row- vs column-major) in Task C2 Step 3 — fix the `FieldView` construction to match `main.py`'s row-major `h*w` layout and re-run.

- [ ] **Step 3: Commit**

```bash
git add cpp_project/tests/equivalence_check.py
git commit -m "Add end-to-end equivalence check vs main.py"
```

---

## Self-Review

**Spec coverage:**
- Python pickle→YAML migration (writer + reader) → Tasks A1, A2.
- YAML schema (field name/dtype string/extra_dims/field_class; fields_to_channels) → A1 Step 1, B4.
- Core library, Ouster-free, libav-only → Tasks B1–B6 (CMake links only `PkgConfig::LIBAV`).
- `add_scan` byte-split + per-channel encoders + aux `.npy` → B6.
- `finalize` bundling videos + npy + metadata.json + metadata.yaml → B6.
- `ChannelEncoder` (gray, libx265, qp/lossless/keyint) → B5.
- `NpyWriter` (.npy v1.0) → B2.
- `TarWriter` (ustar, no libarchive) → B3.
- `YamlMetaWriter` (write-only, no yaml-cpp) → B4.
- pcap CLI front-end with Ouster SDK via FetchContent → C1, C2.
- Nominal frame rate from lidar mode → C2 Step 2.
- Error handling: empty work dir check (B6 ctor), encoder flush on destruct (B5 dtor / finalize) → covered.
- Testing: per-unit cross-checks (B2/B3/B4/B6) + end-to-end equivalence at qp=0 (C3) → covered.

**Placeholder scan:** No "TBD"/"implement later". The two "Note" callouts (ouster-sdk target names in C1; field accessor/layout in C2) are explicit version-dependent risks with concrete fallback instructions and a validating test (C3), not deferred work.

**Type consistency:** `DType`, `FieldView`, `AuxArray`, `FieldTypeMeta`, `ChannelEncoder`, `TarVideoWriter` signatures are defined once (B1/B4/B5/B6) and used consistently in the CLI (C2). `emit_metadata_yaml` signature matches between B4 and B6. `write_npy` signature matches between B2 and B6.

**Open risks (carried from spec):** ouster-sdk FetchContent build cost; container-byte differences (equivalence asserted on decoded frames, not bytes); `field_class` int round-trip — all validated by the C3 equivalence test and the A2 round-trip test.
