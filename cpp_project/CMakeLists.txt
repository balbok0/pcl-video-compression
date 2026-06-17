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
  src/pclvideo/tar_video_writer.cpp
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

add_executable(test_tar_video_writer tests/test_tar_video_writer.cpp)
target_link_libraries(test_tar_video_writer PRIVATE pclvideo doctest::doctest PkgConfig::LIBAV)
add_test(NAME test_tar_video_writer COMMAND test_tar_video_writer)

# --- pcap CLI front-end (the only target that depends on the Ouster SDK) ---
# Guarded so the Ouster-free core library and its tests build independently.
option(PCLVIDEO_BUILD_CLI "Build the pcap-reading pcl2tar CLI (needs Ouster SDK)" ON)
if(PCLVIDEO_BUILD_CLI)
  # ouster-sdk 0.14 bundles an old fmt that fails to compile under C++20 with
  # recent clang (consteval errors). Build the SDK and the CLI that includes its
  # headers as C++17; the Ouster-free core above stays C++20.
  set(CMAKE_CXX_STANDARD 17)
  set(BUILD_VIZ OFF CACHE BOOL "" FORCE)
  set(BUILD_PCAP ON CACHE BOOL "" FORCE)
  set(BUILD_OSF OFF CACHE BOOL "" FORCE)
  set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
  set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(
    ouster_sdk
    GIT_REPOSITORY https://github.com/ouster-lidar/ouster-sdk.git
    GIT_TAG release-0.14.0
    # sdk-extensions is a private submodule not referenced by the CMake build.
    GIT_SUBMODULES ""
  )
  FetchContent_MakeAvailable(ouster_sdk)

  add_executable(pcl2tar src/cli/main.cpp)
  target_link_libraries(pcl2tar PRIVATE pclvideo
    OusterSDK::ouster_client OusterSDK::ouster_pcap)
endif()
