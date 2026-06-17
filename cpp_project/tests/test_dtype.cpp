#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>
#include "pclvideo/dtype.hpp"

using namespace pclvideo;

TEST_CASE("dtype sizes and names") {
    CHECK(dtype_size(DType::U32) == 4);
    CHECK(dtype_size(DType::F64) == 8);
    CHECK(dtype_numpy_name(DType::U32) == "uint32");
    CHECK(dtype_numpy_name(DType::F64) == "float64");
    CHECK(dtype_npy_descr(DType::U32) == "<u4");
    CHECK(dtype_npy_descr(DType::F64) == "<f8");
    CHECK(dtype_from_numpy_name("uint16") == DType::U16);
}
