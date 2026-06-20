#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>
#include "pclvideo/tar_video_writer.hpp"

using namespace pclvideo;

TEST_CASE("writes a tar with the expected members from synthetic scans") {
    const int W = 32, H = 16, N = 4;
    auto work = std::filesystem::temp_directory_path() / "tvw_work";
    std::filesystem::remove_all(work);
    auto out = std::filesystem::temp_directory_path() / "tvw.tar";
    // minimal sensor json
    auto json = std::filesystem::temp_directory_path() / "tvw.json";
    { std::ofstream(json) << "{}"; }

    std::vector<FieldTypeMeta> fts{{"RANGE", DType::U32, {}, 1}};
    TarVideoWriter w(out, work, /*qp=*/0, std::nullopt, 10.0, json, fts);

    std::vector<std::uint32_t> range(static_cast<std::size_t>(W) * H);
    for (int s = 0; s < N; ++s) {
        for (std::size_t k = 0; k < range.size(); ++k)
            range[k] = static_cast<std::uint32_t>(k + s);
        FieldView fv{"RANGE",
                     reinterpret_cast<std::uint8_t*>(range.data()), H, W,
                     DType::U32};
        std::vector<std::uint64_t> ts{static_cast<std::uint64_t>(s)};
        AuxArray aux{"timestamp", reinterpret_cast<std::uint8_t*>(ts.data()),
                     {1}, DType::U64};
        w.add_scan({fv}, {aux}, static_cast<std::uint64_t>(1000 + s));
    }
    w.finalize();
    CHECK(std::filesystem::exists(out));
    CHECK(std::filesystem::file_size(out) % 512 == 0);
}
