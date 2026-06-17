# C++ Implementation Matching `main.py` — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation plan

## Goal

A C++ CLI that converts an Ouster pcap into the same `.tar` artifact the Python
`main.py` produces — byte-exact decoded video frames and equivalent metadata —
structured so the encode/bundle core can later be reused by ROS / ROS2 nodes.

### In scope
- Python metadata migration from pickle to YAML (writer + reader).
- A reusable, input-agnostic C++ core library (byte-split → encode → bundle).
- A pcap-reading CLI front-end that drives the core and matches `main.py`.
- A CMake build that fetches the Ouster C++ SDK for the CLI front-end.

### Out of scope (future work)
- ROS / ROS2 nodes and live-message (non-pcap) input.
- Lossy-compression tuning / quality improvements.
- Any reader changes beyond the YAML migration.

## Background

The current Python pipeline (`main.py`) reads an Ouster pcap, treats each scan
field as a 2-D image, byte-splits multi-byte fields into `uint8` channels,
streams each channel into a per-channel H.265 (libx265) encoder, and bundles the
resulting `.mp4`s plus per-scan auxiliary `.npy` arrays, the sensor
`metadata.json`, and a metadata file into a `.tar`. `PCLVideoReader` reads that
tar back and reconstructs each field.

Two facts drive this design:

1. The tar's metadata file is currently a **Python pickle** of live
   Python/numpy/Ouster objects. Reproducing a valid pickle from C++ is brittle
   (hand-emitting pickle opcodes incl. numpy dtype reconstruction). Decision:
   move to a language-neutral **YAML** file that both languages read/write.

2. The eventual ROS nodes will **not** read pcap — they consume live Ouster
   messages. So pcap reading (and therefore the Ouster C++ SDK) belongs only to
   the CLI front-end, not the reusable core. The core takes frames as plain
   buffers.

## Prerequisite: Python pickle → YAML migration

Performed first, so "match `main.py`" targets a neutral format both languages
share. The reader already imports `yaml`.

- `main.py` writes `_pcl_video_metadata.yaml` instead of `_pcl_video_metadata.pkl`.
- `PCLVideoReader` reads the YAML file.

### YAML schema

```yaml
num_scans: <int>
field_types:
  - name: RANGE
    element_type: uint32        # numpy dtype as a string
    extra_dims: [...]           # list of ints
    field_class: <name-or-int>  # Ouster FieldClass, serialized as name or int
  - ...
fields_to_channels:
  RANGE:
    - [0, uint32]               # [channel_index, original-dtype-string]
    - [1, uint32]
    - ...
  pose:
    - [0, float64]
    - ...
```

### Reader reconstruction changes
- `element_type`: reconstruct with `np.dtype(<string>)` (then `.type` where the
  current code expects a numpy scalar type).
- `field_class`: reconstruct the Ouster `FieldClass` enum from the stored
  name/int.
- `fields_to_channels` per-channel dtype: `np.dtype(<string>)`.

### Verification
Reuse the bounded read-back check already in use: convert the first N scans,
read back through `PCLVideoReader`, assert every field (including `pose`)
reconstructs byte-exact. Behaviour must be unchanged versus the pickle version.

## C++ architecture

Three units with clear boundaries.

### 1. Core library (`pclvideo`) — input-agnostic, no Ouster dependency

Depends only on libav (`libavcodec`, `libavformat`, `libavutil`). Public surface:

- `TarVideoWriter(out_path, qp_level, gop_size, frame_rate, sensor_json_text)`
- `add_scan(...)` — accepts, for one scan: each field as a 2-D buffer
  (pointer + height + width + element dtype), the `pose` buffer, and the four
  auxiliary arrays (`timestamp`, `packet_timestamp`, `status`, `alert_flags`).
  Internally byte-splits each field into `uint8` channels, lazily creates a
  per-`(field, channel)` encoder on first sight, feeds each channel frame to its
  encoder, and writes the aux arrays as per-scan `.npy`.
- `finalize()` — flushes/closes all encoders, then bundles videos + `.npy` +
  `metadata.json` + `metadata.yaml` into the tar.

Internal sub-units, each independently testable:

- `ChannelEncoder` — wraps one libavcodec encoder + libavformat muxer producing
  one `.mp4`. Configures `gray` pixel format, libx265, `qp`, lossless when
  `qp == 0`, and `keyint` when `gop_size` is set.
- `NpyWriter` — emits NumPy `.npy` v1.0 (header + raw little-endian data).
- `TarWriter` — hand-rolled POSIX **ustar** writer. All members are regular
  files, so no `libarchive` dependency.
- `YamlMetaWriter` — emits the fixed metadata schema above. Write-only, so no
  `yaml-cpp` dependency.

### 2. pcap CLI front-end (`pcl2tar`)

Uses the Ouster C++ SDK to read the pcap into scans/fields and drives
`pclvideo`. The only target that depends on Ouster. CLI mirrors `main.py`:
`-i/--input`, `-j/--json-input`, `--qp`, `--gop-size`. Derives the nominal frame
rate from the sensor lidar mode (e.g. `2048x10` → 10), matching `main.py`.

### 3. Build (CMake)

- `FetchContent` pulls and builds `ouster-sdk` (+ transitive deps) for the
  `pcl2tar` target only.
- libav located via `find_package` / pkg-config for the `pclvideo` target.
- `pclvideo` has **zero** Ouster dependency, so future ROS nodes can link it
  directly. (Revisit if isolation proves costly — a direct Ouster dep in the
  core is acceptable to the project owner if needed.)

## Data flow

```
pcap
  → Ouster scans (CLI front-end)
  → core.add_scan(fields, pose, aux)
  → byte-split each field into uint8 channels
  → per-channel libavcodec encode → mux to per-channel .mp4 (work dir)
  → core.finalize()
  → ustar tar { *.mp4, aux .npy, metadata.json, metadata.yaml }
```

## Error handling

- Encoder init / encode / mux failures raise (propagated as exceptions or
  status returns, consistent across the core API).
- `finalize()` and the `TarVideoWriter` destructor guarantee every encoder is
  flushed and closed even on an error path (no half-written `.mp4`).
- The work directory is validated empty before writing (mirrors `main.py`).

## Testing

"Match `main.py`" equivalence check:

1. Convert the first N scans of the demo pcap with the Python `main.py`.
2. Convert the same N scans with the C++ `pcl2tar`.
3. Assert every `.mp4` member decodes **byte-exact** between the two tars at
   `qp = 0` (lossless).
4. Assert `metadata.yaml` agrees on `num_scans`, `field_types`, and
   `fields_to_channels`.

Same harness shape as the bounded checks already used during the Python work.

## Open items / risks

- **Ouster C++ SDK FetchContent build cost.** Heavy first build (Eigen, libtins,
  libpcap, jsoncpp, spdlog, …). Acceptable; isolated to the CLI target.
- **Container muxing differences.** libav's MP4 muxer may produce different
  container bytes than the `ffmpeg` CLI; equivalence is asserted on *decoded
  frames*, not container bytes. Lossless (`qp=0`) must be byte-exact per pixel.
- **`field_class` serialization.** Confirm the exact Ouster enum
  (name vs int) round-trips through YAML in both writer and reader during the
  migration step.
