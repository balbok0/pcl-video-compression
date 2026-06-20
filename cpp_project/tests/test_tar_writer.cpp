#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include <filesystem>
#include "pclvideo/tar_writer.hpp"

using namespace pclvideo;

TEST_CASE("tar writes two members") {
    auto path = std::filesystem::temp_directory_path() / "out.tar";
    {
        TarWriter tw(path);
        std::string a = "hello";
        std::string b = "world!!";
        tw.add_bytes("a.txt", reinterpret_cast<const std::uint8_t*>(a.data()),
                     a.size());
        tw.add_bytes("dir/b.txt",
                     reinterpret_cast<const std::uint8_t*>(b.data()), b.size());
        tw.close();
    }
    // size must be a multiple of 512 (blocked archive)
    CHECK(std::filesystem::file_size(path) % 512 == 0);
}
