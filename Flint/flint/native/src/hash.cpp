/*
 * 面向大文件的流式 SHA-1 / SHA-256。
 *
 * 实现遵循 FIPS 180-4，并在 tests/test_hash.py 中与 Python 的 hashlib
 * 逐字节比对验证。无需引入任何第三方源码。
 */

#include "flint_internal.h"

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace {

constexpr size_t kReadBufferSize = 1024 * 1024;

inline uint32_t rotl32(uint32_t value, int bits) {
    return (value << bits) | (value >> (32 - bits));
}

inline uint32_t rotr32(uint32_t value, int bits) {
    return (value >> bits) | (value << (32 - bits));
}

class Sha1 {
  public:
    Sha1() { reset(); }

    void reset() {
        h_[0] = 0x67452301u;
        h_[1] = 0xEFCDAB89u;
        h_[2] = 0x98BADCFEu;
        h_[3] = 0x10325476u;
        h_[4] = 0xC3D2E1F0u;
        bit_length_ = 0;
        buffer_length_ = 0;
    }

    void update(const uint8_t *data, size_t length) {
        bit_length_ += static_cast<uint64_t>(length) * 8u;
        while (length > 0) {
            const size_t space = 64 - buffer_length_;
            const size_t take = length < space ? length : space;
            std::memcpy(buffer_ + buffer_length_, data, take);
            buffer_length_ += take;
            data += take;
            length -= take;
            if (buffer_length_ == 64) {
                transform(buffer_);
                buffer_length_ = 0;
            }
        }
    }

    void finish(uint8_t out[20]) {
        const uint64_t bit_length = bit_length_;
        const uint8_t pad = 0x80;
        update(&pad, 1);
        const uint8_t zero = 0x00;
        while (buffer_length_ != 56) {
            update(&zero, 1);
        }
        uint8_t length_bytes[8];
        for (int i = 0; i < 8; ++i) {
            length_bytes[7 - i] = static_cast<uint8_t>((bit_length >> (i * 8)) & 0xFF);
        }
        update(length_bytes, 8);
        for (int i = 0; i < 5; ++i) {
            out[i * 4 + 0] = static_cast<uint8_t>(h_[i] >> 24);
            out[i * 4 + 1] = static_cast<uint8_t>(h_[i] >> 16);
            out[i * 4 + 2] = static_cast<uint8_t>(h_[i] >> 8);
            out[i * 4 + 3] = static_cast<uint8_t>(h_[i]);
        }
    }

  private:
    void transform(const uint8_t block[64]) {
        uint32_t w[80];
        for (int i = 0; i < 16; ++i) {
            w[i] = (static_cast<uint32_t>(block[i * 4]) << 24) |
                   (static_cast<uint32_t>(block[i * 4 + 1]) << 16) |
                   (static_cast<uint32_t>(block[i * 4 + 2]) << 8) |
                   static_cast<uint32_t>(block[i * 4 + 3]);
        }
        for (int i = 16; i < 80; ++i) {
            w[i] = rotl32(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
        }

        uint32_t a = h_[0], b = h_[1], c = h_[2], d = h_[3], e = h_[4];
        for (int i = 0; i < 80; ++i) {
            uint32_t f, k;
            if (i < 20) {
                f = (b & c) | ((~b) & d);
                k = 0x5A827999u;
            } else if (i < 40) {
                f = b ^ c ^ d;
                k = 0x6ED9EBA1u;
            } else if (i < 60) {
                f = (b & c) | (b & d) | (c & d);
                k = 0x8F1BBCDCu;
            } else {
                f = b ^ c ^ d;
                k = 0xCA62C1D6u;
            }
            const uint32_t temp = rotl32(a, 5) + f + e + k + w[i];
            e = d;
            d = c;
            c = rotl32(b, 30);
            b = a;
            a = temp;
        }
        h_[0] += a;
        h_[1] += b;
        h_[2] += c;
        h_[3] += d;
        h_[4] += e;
    }

    uint32_t h_[5];
    uint64_t bit_length_;
    uint8_t buffer_[64];
    size_t buffer_length_;
};

const uint32_t kSha256Table[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u,
    0x923f82a4u, 0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
    0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u,
    0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u,
    0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
    0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
    0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au,
    0x5b9cca4fu, 0x682e6ff3u, 0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
    0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u};

class Sha256 {
  public:
    Sha256() { reset(); }

    void reset() {
        h_[0] = 0x6a09e667u;
        h_[1] = 0xbb67ae85u;
        h_[2] = 0x3c6ef372u;
        h_[3] = 0xa54ff53au;
        h_[4] = 0x510e527fu;
        h_[5] = 0x9b05688cu;
        h_[6] = 0x1f83d9abu;
        h_[7] = 0x5be0cd19u;
        bit_length_ = 0;
        buffer_length_ = 0;
    }

    void update(const uint8_t *data, size_t length) {
        bit_length_ += static_cast<uint64_t>(length) * 8u;
        while (length > 0) {
            const size_t space = 64 - buffer_length_;
            const size_t take = length < space ? length : space;
            std::memcpy(buffer_ + buffer_length_, data, take);
            buffer_length_ += take;
            data += take;
            length -= take;
            if (buffer_length_ == 64) {
                transform(buffer_);
                buffer_length_ = 0;
            }
        }
    }

    void finish(uint8_t out[32]) {
        const uint64_t bit_length = bit_length_;
        const uint8_t pad = 0x80;
        update(&pad, 1);
        const uint8_t zero = 0x00;
        while (buffer_length_ != 56) {
            update(&zero, 1);
        }
        uint8_t length_bytes[8];
        for (int i = 0; i < 8; ++i) {
            length_bytes[7 - i] = static_cast<uint8_t>((bit_length >> (i * 8)) & 0xFF);
        }
        update(length_bytes, 8);
        for (int i = 0; i < 8; ++i) {
            out[i * 4 + 0] = static_cast<uint8_t>(h_[i] >> 24);
            out[i * 4 + 1] = static_cast<uint8_t>(h_[i] >> 16);
            out[i * 4 + 2] = static_cast<uint8_t>(h_[i] >> 8);
            out[i * 4 + 3] = static_cast<uint8_t>(h_[i]);
        }
    }

  private:
    void transform(const uint8_t block[64]) {
        uint32_t w[64];
        for (int i = 0; i < 16; ++i) {
            w[i] = (static_cast<uint32_t>(block[i * 4]) << 24) |
                   (static_cast<uint32_t>(block[i * 4 + 1]) << 16) |
                   (static_cast<uint32_t>(block[i * 4 + 2]) << 8) |
                   static_cast<uint32_t>(block[i * 4 + 3]);
        }
        for (int i = 16; i < 64; ++i) {
            const uint32_t s0 =
                rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^ (w[i - 15] >> 3);
            const uint32_t s1 =
                rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }

        uint32_t a = h_[0], b = h_[1], c = h_[2], d = h_[3];
        uint32_t e = h_[4], f = h_[5], g = h_[6], h = h_[7];

        for (int i = 0; i < 64; ++i) {
            const uint32_t s1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
            const uint32_t ch = (e & f) ^ ((~e) & g);
            const uint32_t temp1 = h + s1 + ch + kSha256Table[i] + w[i];
            const uint32_t s0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
            const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            const uint32_t temp2 = s0 + maj;
            h = g;
            g = f;
            f = e;
            e = d + temp1;
            d = c;
            c = b;
            b = a;
            a = temp1 + temp2;
        }

        h_[0] += a;
        h_[1] += b;
        h_[2] += c;
        h_[3] += d;
        h_[4] += e;
        h_[5] += f;
        h_[6] += g;
        h_[7] += h;
    }

    uint32_t h_[8];
    uint64_t bit_length_;
    uint8_t buffer_[64];
    size_t buffer_length_;
};

std::string lowercase(const char *text) {
    std::string value(text);
    for (char &character : value) {
        if (character >= 'A' && character <= 'Z') {
            character = static_cast<char>(character - 'A' + 'a');
        }
    }
    return value;
}

void to_hex(const uint8_t *digest, size_t length, char *out) {
    static const char *kDigits = "0123456789abcdef";
    for (size_t i = 0; i < length; ++i) {
        out[i * 2] = kDigits[digest[i] >> 4];
        out[i * 2 + 1] = kDigits[digest[i] & 0x0F];
    }
    out[length * 2] = '\0';
}

} // namespace

extern "C" int flint_hash_file(const char *path, const char *algo, char *out_hex,
                               size_t out_len) {
    flint::clear_error();

    if (path == nullptr || algo == nullptr || out_hex == nullptr) {
        flint::set_error("flint_hash_file: null argument");
        return FLINT_ERR_INVALID_ARG;
    }
    if (out_len < FLINT_HASH_HEX_SIZE) {
        flint::set_error("flint_hash_file: output buffer too small");
        return FLINT_ERR_INVALID_ARG;
    }

    const std::string algorithm = lowercase(algo);
    const bool use_sha1 = algorithm == "sha1";
    const bool use_sha256 = algorithm == "sha256";
    if (!use_sha1 && !use_sha256) {
        flint::set_error("flint_hash_file: unsupported algorithm '" + algorithm + "'");
        return FLINT_ERR_UNSUPPORTED;
    }

    std::FILE *file = flint::open_file(path, "rb");
    if (file == nullptr) {
        const int saved = errno;
        flint::set_error(std::string("cannot open file: ") + path + ": " +
                         std::strerror(saved));
        return saved == ENOENT ? FLINT_ERR_NOT_FOUND : FLINT_ERR_IO;
    }

    Sha1 sha1;
    Sha256 sha256;
    std::vector<uint8_t> buffer(kReadBufferSize);

    while (true) {
        const size_t read = std::fread(buffer.data(), 1, buffer.size(), file);
        if (read > 0) {
            if (use_sha1) {
                sha1.update(buffer.data(), read);
            } else {
                sha256.update(buffer.data(), read);
            }
        }
        if (read < buffer.size()) {
            if (std::ferror(file) != 0) {
                std::fclose(file);
                flint::set_error(std::string("read error: ") + path);
                return FLINT_ERR_IO;
            }
            break;
        }
    }
    std::fclose(file);

    if (use_sha1) {
        uint8_t digest[20];
        sha1.finish(digest);
        to_hex(digest, sizeof(digest), out_hex);
    } else {
        uint8_t digest[32];
        sha256.finish(digest);
        to_hex(digest, sizeof(digest), out_hex);
    }
    return FLINT_OK;
}
