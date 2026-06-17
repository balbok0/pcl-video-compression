#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include <algorithm>
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
