# PCL Compression as Video

This repo is meant to show a potential structure for compressing continuous point cloud streams, such as LiDAR in context on autonomous driving, drone scans etc.

It is not meant to provide any ability to actually read the created file stream, but serves as a demo, and initial testing for what storage efficiency gains can be made.

## Approach Description

The idea behind this project is very simple, from the perspective of a sensor LiDARs effectively capture range images (+ optionally other channels).
This can be clearly seen with how [ouster sdk](https://static.ouster.dev/sdk-docs/python/examples/lidar-scan.html) represents lidar scans.
It is a massive simplification, since LiDARs by definition are not global shutter and each column/pixel can be received at a different time, which in turn means that image has to be destaggered during reading. However, destagger and additional transformation logic happens when converting sensor scans into point clouds. This demo suggests intercepting scans before this happens, and compressing at this stage.

As such we can treat individual scan as a frame where H is number of beams, W corresponds to `azimuth window * (scan density / degree)`.
For channel information we slice each return type (range, reflectivity, passive near ir, etc...) and timestamp array into a series of single byte (uint8) grayscale videos.
Essentially this means that for uint64 timestamps we will get 8 videos, each having single grayscale uint8 channel.

For ouster specifically this means that [fields in a scan](https://static.ouster.dev/sdk-docs/python/examples/lidar-scan.html)
are represented as:

| Field Name    | dtype  | # of Channels/Videos |
| ------------- | ------ | -------------------- |
| RANGE         | uint32 | 4                    |
| RANGE2        | uint32 | 4                    |
| SIGNAL        | uint16 | 2                    |
| SIGNAL2       | uint16 | 2                    |
| REFLECTIVITY  | uint8  | 1                    |
| REFLECTIVITY2 | uint8  | 1                    |
| NEAR_IR       | uint16 | 2                    |

Then at a read time we decompose them back up into single frame.
This frame can be transformed by `ouster_sdk` into pointclouds,
but that is **not** showcased in this code base.

## Results

For testing we use a demo pcap + json file from [Sample Ouster Data](https://static.ouster.dev/sensor-docs/#sample-data).
Specifically file *OS0 128 Rev 07 Urban Drive (2048x10 Dual Returns)* is used for results below.

### File size reduction

As mentioned above, we do not fully reproduce all of the information in the original pcap file.
That additional information should have minimal effect on file size.

| QP (value)   | File Size | Reduction (%) |
| ------------ | --------- | ------------- |
| Original     | 5.2 GB    |             0 |
| 0 (lossless) | 1.3 GB    |         75.08 |
| 4            | 1.6 GB    |         69.71 |
| 10           | 1.2 GB    |         76.21 |
| 25           | 587M      |         88.96 |

### Runtime

Runtime of script is consistent across all QP values, close to 100s.
Pcap file used in this demonstration is 131s long, so it is faster than real time.
That being said there is a lot of obvious places to optimize code, which should be done if this concept is ever used in production.

### Compression Error

In addition to below table you can run pytest suite to verify that the lossless tar file matches original exactly.

We calculate percent mean absolute error: `100 * abs((original - reconstructed) / original)` across all images.

In general we see that **anything qp>0 produces bad results**.
This is somewhat expected given single field is split into multiple grayscale videos that not compressed together, and error in most significant bits channel will have massive impact on this metric.

I suspect lack of destagger is also causing issues with compression here, since it would make videos more in-sample of the encoders.

| QP | FLAGS | FLAGS2 | NEAR_IR | RANGE | RANGE2 | REFLECTIVITY | REFLECTIVITY2 | SIGNAL | SIGNAL2 |
| -- | ----- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0  | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 4  | 87140118.55250113 | 0.002204173936237348 | 5951845.682940807 | 3.1091980657263936e+16 | 4.578900944563948e+16 | 582021985.3961673 | 799235983.0087618 | 63459.346369945226 | 346342772378.652 |
| 10 | 88717834.20168556 | 0.002204173936237348 | 7588847.5886912 | 5.36335785926133e+16 | 9.064042017683037e+16 | 1195890269.3338394 | 1561855111.454108 | 122645.01831067723 | 751898634790.2797 |
| 25 | 5226524.246064231 | 0.002204173936237348 | 9009223.06007417 | 7.981685911343843e+16 | 1.3895442494276955e+17 | 2272833282.2832723 | 2306268892.862609 | 203293.9293190798 | 1145291028417.2922 |

## Next Steps

Below are, in no particular order, next logical steps for this demo. I will most likely not attempt them, but feel free to fork the repo (or start from scratch) and try them out.

* If interested in lossy compression try not splitting into uint8 grayscale channels, but rather convert into either a colormap or a higher granularity grayscale image.
  * There is also an interesting question of whether video compression can be used for denoising pointclouds. HW accelerated encoders are fast enough to introduce minimal latency to perception pipeline.
* Evaluate compression across different datasets. The ouster demos are nice, but they are city driving which yields nicely to video compression. More esoteric datasets might have smaller gains.
* Write it properly, probably in C++, interfacing directly with ffmpeg sdk.
  * This will be a massive speed-up and probably more reliable than what I'm doing rn (pcap -> folders of pngs -> multiple .mp4 -> .tar)
* Finish up grabbing all of the non-frame properties in the `LidarScan` in `ouster_sdk`. (i.e. long tail)

## Reproduction

1. Create environment - [Download and install uv](https://docs.astral.sh/uv/getting-started/installation/)

## Run on any ouster pcap file
1. Run `uv run main.py <path-to-pcap-file>`

## Reproduce results
1. Download files mentioned above. It should *OS0 128 Rev 07 Urban Drive (2048x10 Dual Returns)* on [Sample Ouster Data](https://static.ouster.dev/sensor-docs/#sample-data). You want to download pcap and metadata json. Place them in the same folder.
1. Run `uv run benchmark.py <path-to-pcap-file>`
