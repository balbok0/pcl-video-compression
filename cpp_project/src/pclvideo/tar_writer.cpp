#include "pclvideo/tar_writer.hpp"
#include <cstring>
#include <iterator>
#include <stdexcept>
#include <vector>

namespace pclvideo {
namespace {

void octal(char* field, std::size_t width, std::uint64_t value) {
    // width includes the trailing space/NUL terminator slot.
    std::memset(field, '0', width - 1);
    field[width - 1] = '\0';
    for (std::size_t i = width - 1; i-- > 0;) {
        field[i] = static_cast<char>('0' + (value & 7));
        value >>= 3;
    }
}

}  // namespace

TarWriter::TarWriter(const std::filesystem::path& out_path)
    : out_(out_path, std::ios::binary) {
    if (!out_) throw std::runtime_error("cannot open tar: " + out_path.string());
}

TarWriter::~TarWriter() {
    if (!closed_) {
        try { close(); } catch (...) {}
    }
}

void TarWriter::write_header(const std::string& arcname, std::size_t size) {
    if (arcname.size() > 100)
        throw std::runtime_error("arcname too long for ustar: " + arcname);

    char hdr[512];
    std::memset(hdr, 0, sizeof(hdr));
    std::memcpy(hdr, arcname.data(), arcname.size());      // name[100] @0
    octal(hdr + 100, 8, 0644);                             // mode[8] @100
    octal(hdr + 108, 8, 0);                                // uid[8] @108
    octal(hdr + 116, 8, 0);                                // gid[8] @116
    octal(hdr + 124, 12, size);                            // size[12] @124
    octal(hdr + 136, 12, 0);                               // mtime[12] @136
    std::memset(hdr + 148, ' ', 8);                        // chksum placeholder
    hdr[156] = '0';                                        // typeflag = regular
    std::memcpy(hdr + 257, "ustar", 5);                    // magic[6] @257
    hdr[263] = '0'; hdr[264] = '0';                        // version "00"

    unsigned chksum = 0;
    for (int i = 0; i < 512; ++i)
        chksum += static_cast<unsigned char>(hdr[i]);
    octal(hdr + 148, 7, chksum);                           // 6 digits + NUL
    hdr[155] = ' ';

    out_.write(hdr, 512);
}

void TarWriter::add_bytes(const std::string& arcname, const std::uint8_t* data,
                          std::size_t size) {
    write_header(arcname, size);
    out_.write(reinterpret_cast<const char*>(data),
               static_cast<std::streamsize>(size));
    std::size_t pad = (512 - (size % 512)) % 512;
    static const char zeros[512] = {0};
    if (pad) out_.write(zeros, static_cast<std::streamsize>(pad));
}

void TarWriter::add_file(const std::string& arcname,
                         const std::filesystem::path& src) {
    std::ifstream in(src, std::ios::binary);
    if (!in) throw std::runtime_error("cannot read " + src.string());
    std::vector<char> buf((std::istreambuf_iterator<char>(in)), {});
    add_bytes(arcname, reinterpret_cast<const std::uint8_t*>(buf.data()),
              buf.size());
}

void TarWriter::close() {
    if (closed_) return;
    static const char zeros[512] = {0};
    out_.write(zeros, 512);  // two zero blocks mark end-of-archive
    out_.write(zeros, 512);
    out_.flush();
    closed_ = true;
}

}  // namespace pclvideo
