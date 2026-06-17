#pragma once
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace pclvideo {

// Minimal POSIX ustar writer. All members are regular files. Uncompressed,
// matching Python's tarfile.TarFile(mode="w").
class TarWriter {
public:
    explicit TarWriter(const std::filesystem::path& out_path);
    ~TarWriter();

    void add_bytes(const std::string& arcname, const std::uint8_t* data,
                   std::size_t size);
    void add_file(const std::string& arcname,
                  const std::filesystem::path& src);
    void close();

private:
    void write_header(const std::string& arcname, std::size_t size);
    std::ofstream out_;
    bool closed_ = false;
};

}  // namespace pclvideo
