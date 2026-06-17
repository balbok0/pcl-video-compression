#include "pclvideo/channel_encoder.hpp"
#include <algorithm>
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
    // time_base = 1/fps so each frame advances pts by exactly one tick.
    cctx_->framerate = av_d2q(frame_rate, 100000);
    cctx_->time_base = AVRational{cctx_->framerate.den, cctx_->framerate.num};
    // No B-frames: avoids reorder/edit-list issues in MP4 that drop a frame on
    // decode. Lossless pixel content is unaffected.
    cctx_->max_b_frames = 0;
    if (gop_size) cctx_->gop_size = *gop_size;
    if (fmt_->oformat->flags & AVFMT_GLOBALHEADER)
        cctx_->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;

    av_opt_set(cctx_->priv_data, "preset", "ultrafast", 0);
    av_opt_set_int(cctx_->priv_data, "qp", qp_level, 0);
    // log-level=none silences libx265's own info/summary output (it bypasses
    // libav's logging).
    std::string x265 = "log-level=none:bframes=0";
    if (qp_level == 0) x265 += ":lossless=1";
    if (gop_size)
        x265 += (x265.empty() ? "" : ":") + ("keyint=" + std::to_string(*gop_size));
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
        pkt_->duration = 1;  // one frame in cctx_ time_base (1/fps)
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
    frame_->pts = pts_++;  // one tick per frame in cctx_ time_base (1/fps)
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
