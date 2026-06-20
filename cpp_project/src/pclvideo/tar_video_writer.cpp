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
