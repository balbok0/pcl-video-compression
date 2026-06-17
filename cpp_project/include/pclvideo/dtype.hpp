#pragma once
#include <cstddef>
#include <string>

namespace pclvideo {

enum class DType { U8, U16, U32, U64, I8, I16, I32, I64, F32, F64 };

// Byte width of one element.
std::size_t dtype_size(DType dt);

// NumPy name, e.g. "uint32" — matches numpy.dtype(...).name.
std::string dtype_numpy_name(DType dt);

// NumPy little-endian descr, e.g. "<u4" — for .npy headers.
std::string dtype_npy_descr(DType dt);

// Parse a numpy name ("uint32") into a DType. Throws std::invalid_argument.
DType dtype_from_numpy_name(const std::string& name);

}  // namespace pclvideo
