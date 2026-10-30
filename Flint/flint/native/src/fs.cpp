/* 文件辅助：支持 UTF-8 的 fopen()、分块复制与原子写支撑。 */

#include "flint_internal.h"

#include <cerrno>
#include <cstring>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

constexpr size_t kCopyBufferSize = 1024 * 1024;

#ifdef _WIN32
std::wstring utf8_to_wide(const char *text) {
    if (text == nullptr) {
        return std::wstring();
    }
    const int length = ::MultiByteToWideChar(CP_UTF8, 0, text, -1, nullptr, 0);
    if (length <= 0) {
        return std::wstring();
    }
    std::wstring wide(static_cast<size_t>(length - 1), L'\0');
    if (::MultiByteToWideChar(CP_UTF8, 0, text, -1, &wide[0], length) != length) {
        return std::wstring();
    }
    return wide;
}
#endif

int report_open_error(const char *path, int saved_errno) {
    flint::set_error(std::string("cannot open '") + path + "': " + std::strerror(saved_errno));
    return saved_errno == ENOENT ? FLINT_ERR_NOT_FOUND : FLINT_ERR_IO;
}

} // namespace

namespace flint {

std::FILE *open_file(const char *path, const char *mode) {
    if (path == nullptr || mode == nullptr) {
        return nullptr;
    }
#ifdef _WIN32
    const std::wstring wide_path = utf8_to_wide(path);
    const std::wstring wide_mode = utf8_to_wide(mode);
    if (wide_path.empty() || wide_mode.empty()) {
        return nullptr;
    }
    return ::_wfopen(wide_path.c_str(), wide_mode.c_str());
#else
    return std::fopen(path, mode);
#endif
}

} // namespace flint

extern "C" int flint_copy_file(const char *src, const char *dst, flint_cancel_fn cancel_fn,
                               void *user_data) {
    flint::clear_error();

    if (src == nullptr || dst == nullptr) {
        flint::set_error("flint_copy_file: null argument");
        return FLINT_ERR_INVALID_ARG;
    }

    std::FILE *input = flint::open_file(src, "rb");
    if (input == nullptr) {
        return report_open_error(src, errno);
    }
    std::FILE *output = flint::open_file(dst, "wb");
    if (output == nullptr) {
        const int saved = errno;
        std::fclose(input);
        return report_open_error(dst, saved);
    }

    std::vector<unsigned char> buffer(kCopyBufferSize);
    int status = FLINT_OK;

    while (true) {
        if (flint::cancelled(cancel_fn, user_data)) {
            flint::set_error(std::string("copy cancelled: ") + src);
            status = FLINT_ERR_CANCELLED;
            break;
        }

        const size_t read = std::fread(buffer.data(), 1, buffer.size(), input);
        if (read > 0 && std::fwrite(buffer.data(), 1, read, output) != read) {
            flint::set_error(std::string("write failed: ") + dst + ": " + std::strerror(errno));
            status = FLINT_ERR_IO;
            break;
        }
        if (read < buffer.size()) {
            if (std::ferror(input) != 0) {
                flint::set_error(std::string("read failed: ") + src + ": " + std::strerror(errno));
                status = FLINT_ERR_IO;
            }
            break;
        }
    }

    if (std::fflush(output) != 0 && status == FLINT_OK) {
        flint::set_error(std::string("flush failed: ") + dst + ": " + std::strerror(errno));
        status = FLINT_ERR_IO;
    }
    if (std::fclose(output) != 0 && status == FLINT_OK) {
        flint::set_error(std::string("close failed: ") + dst + ": " + std::strerror(errno));
        status = FLINT_ERR_IO;
    }
    std::fclose(input);
    return status;
}
