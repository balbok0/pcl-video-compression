#pragma once
#include <map>
#include <string>
#include <utility>
#include <vector>
#include "pclvideo/dtype.hpp"

namespace pclvideo {

struct FieldTypeMeta {
    std::string name;
    DType element_type;
    std::vector<int> extra_dims;
    int field_class;
};

// Emits the fixed metadata schema matching main.py's YAML. Returns the document
// as a string (so it can be added to the tar without a temp file).
std::string emit_metadata_yaml(
    int num_scans,
    const std::vector<FieldTypeMeta>& field_types,
    const std::map<std::string, std::vector<std::pair<int, DType>>>&
        fields_to_channels);

}  // namespace pclvideo
