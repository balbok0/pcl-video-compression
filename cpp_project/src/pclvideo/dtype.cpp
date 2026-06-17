#include "pclvideo/dtype.hpp"
#include <stdexcept>

namespace pclvideo {

std::size_t dtype_size(DType dt) {
    switch (dt) {
        case DType::U8: case DType::I8: return 1;
        case DType::U16: case DType::I16: return 2;
        case DType::U32: case DType::I32: case DType::F32: return 4;
        case DType::U64: case DType::I64: case DType::F64: return 8;
    }
    throw std::invalid_argument("unknown dtype");
}

std::string dtype_numpy_name(DType dt) {
    switch (dt) {
        case DType::U8: return "uint8";   case DType::U16: return "uint16";
        case DType::U32: return "uint32"; case DType::U64: return "uint64";
        case DType::I8: return "int8";    case DType::I16: return "int16";
        case DType::I32: return "int32";  case DType::I64: return "int64";
        case DType::F32: return "float32";case DType::F64: return "float64";
    }
    throw std::invalid_argument("unknown dtype");
}

std::string dtype_npy_descr(DType dt) {
    switch (dt) {
        case DType::U8: return "|u1";   case DType::U16: return "<u2";
        case DType::U32: return "<u4";  case DType::U64: return "<u8";
        case DType::I8: return "|i1";   case DType::I16: return "<i2";
        case DType::I32: return "<i4";  case DType::I64: return "<i8";
        case DType::F32: return "<f4";  case DType::F64: return "<f8";
    }
    throw std::invalid_argument("unknown dtype");
}

DType dtype_from_numpy_name(const std::string& name) {
    if (name == "uint8") return DType::U8;
    if (name == "uint16") return DType::U16;
    if (name == "uint32") return DType::U32;
    if (name == "uint64") return DType::U64;
    if (name == "int8") return DType::I8;
    if (name == "int16") return DType::I16;
    if (name == "int32") return DType::I32;
    if (name == "int64") return DType::I64;
    if (name == "float32") return DType::F32;
    if (name == "float64") return DType::F64;
    throw std::invalid_argument("unknown numpy name: " + name);
}

}  // namespace pclvideo
