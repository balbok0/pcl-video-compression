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
