#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include <filesystem>
#include <fstream>
#include "pclvideo/yaml_meta_writer.hpp"

using namespace pclvideo;

TEST_CASE("yaml metadata contains expected keys and values") {
    std::vector<FieldTypeMeta> fts{
        {"RANGE", DType::U32, {}, 1},
    };
    std::map<std::string, std::vector<std::pair<int, DType>>> ftc{
        {"RANGE", {{0, DType::U32}, {1, DType::U32}}},
        {"pose", {{0, DType::F64}}},
    };
    std::string doc = emit_metadata_yaml(7, fts, ftc);
    CHECK(doc.find("num_scans: 7") != std::string::npos);
    CHECK(doc.find("name: RANGE") != std::string::npos);
    CHECK(doc.find("element_type: uint32") != std::string::npos);
    CHECK(doc.find("field_class: 1") != std::string::npos);
    CHECK(doc.find("pose:") != std::string::npos);
    CHECK(doc.find("- [0, float64]") != std::string::npos);

    // Dump for the Python pyyaml cross-check.
    std::ofstream(std::filesystem::temp_directory_path() / "meta.yaml") << doc;
}
