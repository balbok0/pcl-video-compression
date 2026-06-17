#pragma once
#include <cstdint>
#include <filesystem>
#include <vector>
#include "pclvideo/dtype.hpp"

namespace pclvideo {

// Writes a NumPy .npy v1.0 file (little-endian, C-order).
void write_npy(const std::filesystem::path& path,
               const std::uint8_t* data,
               const std::vector<std::size_t>& shape,
               DType dtype);

}  // namespace pclvideo
