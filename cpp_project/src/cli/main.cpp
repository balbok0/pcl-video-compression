#include <cstdint>
#include <filesystem>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <vector>

#include <ouster/field.h>
#include <ouster/lidar_scan.h>
#include <ouster/os_pcap.h>
#include <ouster/types.h>

#include "pclvideo/tar_video_writer.hpp"

namespace cf = ouster::sensor;
namespace su = ouster::sensor_utils;

static pclvideo::DType to_dtype(cf::ChanFieldType t) {
    using CFT = cf::ChanFieldType;
    switch (t) {
        case CFT::UINT8: return pclvideo::DType::U8;
        case CFT::UINT16: return pclvideo::DType::U16;
        case CFT::UINT32: return pclvideo::DType::U32;
        case CFT::UINT64: return pclvideo::DType::U64;
        case CFT::INT8: return pclvideo::DType::I8;
        case CFT::INT16: return pclvideo::DType::I16;
        case CFT::INT32: return pclvideo::DType::I32;
        case CFT::INT64: return pclvideo::DType::I64;
        case CFT::FLOAT32: return pclvideo::DType::F32;
        case CFT::FLOAT64: return pclvideo::DType::F64;
        default: throw std::runtime_error("unsupported ChanFieldType");
    }
}

// Raw row-major byte pointer into the scan's storage for a named field.
static const std::uint8_t* field_bytes(ouster::LidarScan& s,
                                        const std::string& n,
                                        cf::ChanFieldType t) {
    using CFT = cf::ChanFieldType;
    switch (t) {
        case CFT::UINT8:  return reinterpret_cast<const std::uint8_t*>(s.field<std::uint8_t>(n).data());
        case CFT::UINT16: return reinterpret_cast<const std::uint8_t*>(s.field<std::uint16_t>(n).data());
        case CFT::UINT32: return reinterpret_cast<const std::uint8_t*>(s.field<std::uint32_t>(n).data());
        case CFT::UINT64: return reinterpret_cast<const std::uint8_t*>(s.field<std::uint64_t>(n).data());
        case CFT::INT8:   return reinterpret_cast<const std::uint8_t*>(s.field<std::int8_t>(n).data());
        case CFT::INT16:  return reinterpret_cast<const std::uint8_t*>(s.field<std::int16_t>(n).data());
        case CFT::INT32:  return reinterpret_cast<const std::uint8_t*>(s.field<std::int32_t>(n).data());
        case CFT::INT64:  return reinterpret_cast<const std::uint8_t*>(s.field<std::int64_t>(n).data());
        case CFT::FLOAT32:return reinterpret_cast<const std::uint8_t*>(s.field<float>(n).data());
        case CFT::FLOAT64:return reinterpret_cast<const std::uint8_t*>(s.field<double>(n).data());
        default: throw std::runtime_error("unsupported ChanFieldType");
    }
}

// Nominal fps from lidar mode, e.g. "2048x10" -> 10.
static double frame_rate_from_mode(const cf::sensor_info& si) {
    if (!si.config.lidar_mode) return 10.0;
    std::string s = cf::to_string(*si.config.lidar_mode);
    auto x = s.rfind('x');
    return x == std::string::npos ? 10.0 : std::stod(s.substr(x + 1));
}

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

    auto info = cf::metadata_from_json(json);
    const cf::packet_format& pf = cf::get_format(info);
    const std::size_t lidar_packet_size = pf.lidar_packet_size;

    ouster::LidarScan scan(info);
    ouster::ScanBatcher batch(info);

    // Field-type metadata (sensor fields only; pose is added during streaming,
    // matching main.py).
    std::vector<pclvideo::FieldTypeMeta> field_types;
    for (const auto& ft : scan.field_types()) {
        std::vector<int> ed(ft.extra_dims.begin(), ft.extra_dims.end());
        field_types.push_back({ft.name, to_dtype(ft.element_type), ed,
                                static_cast<int>(ft.field_class)});
    }

    std::filesystem::path out =
        std::filesystem::path(pcap).replace_extension(".tar");
    std::filesystem::path work =
        std::filesystem::temp_directory_path() /
        ("pcl2tar_" + std::to_string(::getpid()));
    pclvideo::TarVideoWriter writer(out, work, qp, gop,
                                    frame_rate_from_mode(info), json,
                                    field_types);

    auto handle = su::replay_initialize(pcap);
    su::packet_info pi;
    std::vector<std::uint8_t> buf(65536);

    while (su::next_packet_info(*handle, pi)) {
        std::size_t n = su::read_packet(*handle, buf.data(), buf.size());
        if (n != lidar_packet_size) continue;     // skip imu/other packets
        // 3-arg overload stamps each packet with the pcap capture time (ns) so
        // packet_timestamp() / get_first_valid_packet_timestamp() are populated.
        std::uint64_t host_ts =
            static_cast<std::uint64_t>(pi.timestamp.count()) * 1000ULL;
        if (!batch(buf.data(), host_ts, scan)) continue;  // scan not complete

        std::uint64_t ts = scan.get_first_valid_packet_timestamp();
        if (ts == 0) continue;

        const int H = static_cast<int>(scan.h);
        const int W = static_cast<int>(scan.w);

        std::vector<pclvideo::FieldView> fields;
        for (const auto& ft : scan.field_types()) {
            fields.push_back({ft.name,
                              field_bytes(scan, ft.name, ft.element_type), H, W,
                              to_dtype(ft.element_type)});
        }
        // pose: (w, 4, 4) doubles == (w, 16) image, matching main.py.
        fields.push_back({"pose",
                          reinterpret_cast<const std::uint8_t*>(
                              scan.pose().get<double>()),
                          W, 16, pclvideo::DType::F64});

        std::vector<pclvideo::AuxArray> aux;
        auto ts_h = scan.timestamp();
        aux.push_back({"timestamp",
                       reinterpret_cast<const std::uint8_t*>(ts_h.data()),
                       {static_cast<std::size_t>(ts_h.size())},
                       pclvideo::DType::U64});
        auto pts_h = scan.packet_timestamp();
        aux.push_back({"packet_timestamp",
                       reinterpret_cast<const std::uint8_t*>(pts_h.data()),
                       {static_cast<std::size_t>(pts_h.size())},
                       pclvideo::DType::U64});
        auto st_h = scan.status();
        aux.push_back({"status",
                       reinterpret_cast<const std::uint8_t*>(st_h.data()),
                       {static_cast<std::size_t>(st_h.size())},
                       pclvideo::DType::U32});
        auto af_h = scan.alert_flags();
        aux.push_back({"alert_flags",
                       reinterpret_cast<const std::uint8_t*>(af_h.data()),
                       {static_cast<std::size_t>(af_h.size())},
                       pclvideo::DType::U8});

        writer.add_scan(fields, aux, ts);
    }
    writer.finalize();
    std::cout << "wrote " << out << "\n";
    return 0;
}
