/* 基于 miniz 的 ZIP 解压，并在写入前做 Zip Slip 校验。 */

#include "flint_internal.h"

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cstring>
#include <filesystem>
#include <string>
#include <vector>

#include "miniz.h"

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

namespace fs = std::filesystem;

#ifdef _WIN32
std::wstring utf8_to_wide(const std::string &text) {
    if (text.empty()) {
        return std::wstring();
    }
    const int length =
        ::MultiByteToWideChar(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()), nullptr, 0);
    if (length <= 0) {
        return std::wstring();
    }
    std::wstring wide(static_cast<size_t>(length), L'\0');
    ::MultiByteToWideChar(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()), &wide[0], length);
    return wide;
}
#endif

fs::path path_from_utf8(const std::string &text) {
#ifdef _WIN32
    return fs::path(utf8_to_wide(text));
#else
    return fs::path(text);
#endif
}

bool ensure_directories(const std::string &path_utf8) {
    if (path_utf8.empty()) {
        return true;
    }
    std::error_code error;
    fs::create_directories(path_from_utf8(path_utf8), error);
    return !error;
}

std::string parent_of(const std::string &path_utf8) {
    const size_t position = path_utf8.find_last_of("/\\");
    if (position == std::string::npos) {
        return std::string();
    }
    return path_utf8.substr(0, position);
}

std::string join_path(const std::string &directory, const std::string &name) {
    if (directory.empty()) {
        return name;
    }
    const char last = directory.back();
    if (last == '/' || last == '\\') {
        return directory + name;
    }
    return directory + "/" + name;
}

/* 拒绝绝对路径、盘符以及含 ".." 的路径分量。 */
bool normalize_member(const char *raw_name, std::string *normalized) {
    if (raw_name == nullptr) {
        return false;
    }
    std::string name(raw_name);
    if (name.empty() || name.find('\0') != std::string::npos) {
        return false;
    }
    std::replace(name.begin(), name.end(), '\\', '/');
    if (name.front() == '/') {
        return false;
    }
    if (name.size() >= 2 && name[1] == ':' &&
        std::isalpha(static_cast<unsigned char>(name[0])) != 0) {
        return false;
    }

    size_t start = 0;
    while (start <= name.size()) {
        size_t end = name.find('/', start);
        if (end == std::string::npos) {
            end = name.size();
        }
        const std::string component = name.substr(start, end - start);
        if (component == "..") {
            return false;
        }
        if (end == name.size()) {
            break;
        }
        start = end + 1;
    }

    *normalized = name;
    return true;
}

int seek_file(std::FILE *file, uint64_t offset) {
#ifdef _WIN32
    return ::_fseeki64(file, static_cast<__int64>(offset), SEEK_SET);
#else
    return ::fseeko(file, static_cast<off_t>(offset), SEEK_SET);
#endif
}

struct FileWriter {
    std::FILE *file = nullptr;
    uint64_t written = 0;
    flint_cancel_fn cancel_fn = nullptr;
    void *user_data = nullptr;
    bool aborted = false;
};

size_t write_callback(void *opaque, mz_uint64 file_ofs, const void *buffer, size_t size) {
    auto *writer = static_cast<FileWriter *>(opaque);
    if (flint::cancelled(writer->cancel_fn, writer->user_data)) {
        writer->aborted = true;
        return 0;
    }
    if (file_ofs != writer->written && seek_file(writer->file, file_ofs) != 0) {
        return 0;
    }
    const size_t written = std::fwrite(buffer, 1, size, writer->file);
    writer->written += written;
    return written;
}

/* RAII 守卫：保证任何返回路径都会关闭压缩包与输入文件。 */
struct ArchiveGuard {
    mz_zip_archive archive{};
    std::FILE *file = nullptr;
    bool opened = false;

    ~ArchiveGuard() {
        if (opened) {
            mz_zip_reader_end(&archive);
        }
        if (file != nullptr) {
            std::fclose(file);
        }
    }
};

} // namespace

extern "C" int flint_extract_zip(const char *zip_path, const char *dest_dir,
                                 flint_cancel_fn cancel_fn, void *user_data) {
    flint::clear_error();

    if (zip_path == nullptr || dest_dir == nullptr) {
        flint::set_error("flint_extract_zip: null argument");
        return FLINT_ERR_INVALID_ARG;
    }

    ArchiveGuard guard;
    guard.file = flint::open_file(zip_path, "rb");
    if (guard.file == nullptr) {
        const int saved = errno;
        flint::set_error(std::string("cannot open archive '") + zip_path +
                         "': " + std::strerror(saved));
        return saved == ENOENT ? FLINT_ERR_NOT_FOUND : FLINT_ERR_IO;
    }

    if (::fseek(guard.file, 0, SEEK_END) != 0) {
        flint::set_error(std::string("cannot size archive: ") + zip_path);
        return FLINT_ERR_IO;
    }
#ifdef _WIN32
    const auto archive_size = static_cast<mz_uint64>(::_ftelli64(guard.file));
#else
    const auto archive_size = static_cast<mz_uint64>(::ftello(guard.file));
#endif
    if (::fseek(guard.file, 0, SEEK_SET) != 0) {
        flint::set_error(std::string("cannot rewind archive: ") + zip_path);
        return FLINT_ERR_IO;
    }

    if (mz_zip_reader_init_cfile(&guard.archive, guard.file, archive_size, 0) != MZ_TRUE) {
        flint::set_error(std::string("not a readable zip archive: ") + zip_path);
        return FLINT_ERR_ZIP;
    }
    guard.opened = true;

    const std::string destination(dest_dir);
    if (!ensure_directories(destination)) {
        flint::set_error(std::string("cannot create directory: ") + destination);
        return FLINT_ERR_IO;
    }

    const mz_uint count = mz_zip_reader_get_num_files(&guard.archive);
    std::vector<std::string> names(count);
    std::vector<mz_bool> is_directory(count);

    for (mz_uint index = 0; index < count; ++index) {
        mz_zip_archive_file_stat stat{};
        if (mz_zip_reader_file_stat(&guard.archive, index, &stat) != MZ_TRUE) {
            flint::set_error(std::string("cannot read zip entry #") + std::to_string(index));
            return FLINT_ERR_ZIP;
        }
        std::string normalized;
        if (!normalize_member(stat.m_filename, &normalized)) {
            flint::set_error(std::string("unsafe archive member: ") + stat.m_filename);
            return FLINT_ERR_PATH_TRAVERSAL;
        }
        names[index] = normalized;
        is_directory[index] = stat.m_is_directory;
    }

    for (mz_uint index = 0; index < count; ++index) {
        if (flint::cancelled(cancel_fn, user_data)) {
            flint::set_error("zip extraction cancelled");
            return FLINT_ERR_CANCELLED;
        }

        const std::string target = join_path(destination, names[index]);
        if (is_directory[index] != MZ_FALSE) {
            if (!ensure_directories(target)) {
                flint::set_error(std::string("cannot create directory: ") + target);
                return FLINT_ERR_IO;
            }
            continue;
        }

        if (!ensure_directories(parent_of(target))) {
            flint::set_error(std::string("cannot create directory for: ") + target);
            return FLINT_ERR_IO;
        }

        std::FILE *output = flint::open_file(target.c_str(), "wb");
        if (output == nullptr) {
            const int saved = errno;
            flint::set_error(std::string("cannot write '") + target +
                             "': " + std::strerror(saved));
            return FLINT_ERR_IO;
        }

        FileWriter writer{output, 0, cancel_fn, user_data, false};
        const mz_bool ok =
            mz_zip_reader_extract_to_callback(&guard.archive, index, write_callback, &writer, 0);
        const bool flush_failed = std::fflush(output) != 0;
        std::fclose(output);

        if (writer.aborted) {
            std::error_code ignored;
            fs::remove(path_from_utf8(target), ignored);
            flint::set_error("zip extraction cancelled");
            return FLINT_ERR_CANCELLED;
        }
        if (ok != MZ_TRUE || flush_failed) {
            std::error_code ignored;
            fs::remove(path_from_utf8(target), ignored);
            flint::set_error(std::string("failed to extract: ") + names[index]);
            return FLINT_ERR_ZIP;
        }
    }

    return FLINT_OK;
}
