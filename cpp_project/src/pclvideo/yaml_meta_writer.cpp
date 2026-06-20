#include "pclvideo/yaml_meta_writer.hpp"
#include <sstream>

namespace pclvideo {

std::string emit_metadata_yaml(
    int num_scans, const std::vector<FieldTypeMeta>& field_types,
    const std::map<std::string, std::vector<std::pair<int, DType>>>&
        fields_to_channels) {
    std::ostringstream o;
    o << "num_scans: " << num_scans << "\n";

    o << "field_types:\n";
    for (const auto& ft : field_types) {
        o << "- name: " << ft.name << "\n";
        o << "  element_type: " << dtype_numpy_name(ft.element_type) << "\n";
        o << "  extra_dims: [";
        for (std::size_t i = 0; i < ft.extra_dims.size(); ++i) {
            o << ft.extra_dims[i];
            if (i + 1 < ft.extra_dims.size()) o << ", ";
        }
        o << "]\n";
        o << "  field_class: " << ft.field_class << "\n";
    }

    o << "fields_to_channels:\n";
    for (const auto& [field, channels] : fields_to_channels) {
        o << "  " << field << ":\n";
        for (const auto& [ch, dt] : channels) {
            o << "  - [" << ch << ", " << dtype_numpy_name(dt) << "]\n";
        }
    }
    return o.str();
}

}  // namespace pclvideo
