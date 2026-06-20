#include "pclvideo/npy_writer.hpp"
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace pclvideo {

void write_npy(const std::filesystem::path& path, const std::uint8_t* data,
               const std::vector<std::size_t>& shape, DType dtype) {
    std::ostringstream shape_ss;
    shape_ss << "(";
    for (std::size_t i = 0; i < shape.size(); ++i) {
        shape_ss << shape[i];
        if (shape.size() == 1 || i + 1 < shape.size()) shape_ss << ", ";
    }
    shape_ss << ")";

    std::ostringstream hdr;
    hdr << "{'descr': '" << dtype_npy_descr(dtype)
        << "', 'fortran_order': False, 'shape': " << shape_ss.str() << ", }";
    std::string header = hdr.str();

    // Pad with spaces so that 10 + header_len is a multiple of 64, ending in \n.
    std::size_t base = 10 + header.size() + 1;  // +1 for trailing newline
    std::size_t pad = (64 - (base % 64)) % 64;
    header.append(pad, ' ');
    header.push_back('\n');

    std::uint16_t hlen = static_cast<std::uint16_t>(header.size());

    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("cannot open " + path.string());
    f.put('\x93');
    f.write("NUMPY", 5);
    f.put(1);  // major
    f.put(0);  // minor
    f.put(static_cast<char>(hlen & 0xff));
    f.put(static_cast<char>((hlen >> 8) & 0xff));
    f.write(header.data(), header.size());

    std::size_t count = 1;
    for (std::size_t d : shape) count *= d;
    f.write(reinterpret_cast<const char*>(data),
            static_cast<std::streamsize>(count * dtype_size(dtype)));
}

}  // namespace pclvideo
