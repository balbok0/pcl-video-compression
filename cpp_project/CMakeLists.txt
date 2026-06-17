cmake_minimum_required(VERSION 3.24)
project(pclvideo_project LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Allow FetchContent deps whose CMakeLists predate CMake 3.5's policy floor
# (doctest 2.4.11, ouster-sdk, etc.) to configure under CMake 4.x.
set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "" FORCE)

find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET
  libavcodec libavformat libavutil)

include(FetchContent)
FetchContent_Declare(
  doctest
  GIT_REPOSITORY https://github.com/doctest/doctest.git
  GIT_TAG v2.4.11
)
FetchContent_MakeAvailable(doctest)

# Core library (no Ouster dependency).
add_library(pclvideo
  src/pclvideo/dtype.cpp
  src/pclvideo/npy_writer.cpp
  src/pclvideo/tar_writer.cpp
  src/pclvideo/yaml_meta_writer.cpp
  src/pclvideo/channel_encoder.cpp
)
target_include_directories(pclvideo PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(pclvideo PUBLIC PkgConfig::LIBAV)

enable_testing()
add_executable(test_dtype tests/test_dtype.cpp)
target_link_libraries(test_dtype PRIVATE pclvideo doctest::doctest)
add_test(NAME test_dtype COMMAND test_dtype)

add_executable(test_npy_writer tests/test_npy_writer.cpp)
target_link_libraries(test_npy_writer PRIVATE pclvideo doctest::doctest)
add_test(NAME test_npy_writer COMMAND test_npy_writer)

add_executable(test_tar_writer tests/test_tar_writer.cpp)
target_link_libraries(test_tar_writer PRIVATE pclvideo doctest::doctest)
add_test(NAME test_tar_writer COMMAND test_tar_writer)

add_executable(test_yaml_meta_writer tests/test_yaml_meta_writer.cpp)
target_link_libraries(test_yaml_meta_writer PRIVATE pclvideo doctest::doctest)
add_test(NAME test_yaml_meta_writer COMMAND test_yaml_meta_writer)

add_executable(test_channel_encoder tests/test_channel_encoder.cpp)
target_link_libraries(test_channel_encoder PRIVATE pclvideo doctest::doctest PkgConfig::LIBAV)
add_test(NAME test_channel_encoder COMMAND test_channel_encoder)
