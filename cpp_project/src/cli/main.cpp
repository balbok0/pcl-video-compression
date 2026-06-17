#include <iostream>
#include <optional>
#include <string>

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
    std::string mode = info.config.lidar_mode
                           ? ouster::sensor::to_string(*info.config.lidar_mode)
                           : "unknown";
    std::cout << "opened sensor: " << info.prod_line << " mode=" << mode << "\n";
    return 0;
}
