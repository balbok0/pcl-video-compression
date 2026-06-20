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
