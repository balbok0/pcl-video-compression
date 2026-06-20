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
