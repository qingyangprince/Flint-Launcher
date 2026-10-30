/*
 * flint_native.h —— Flint 原生辅助库的稳定 C ABI。
 *
 * 该库是可选的：当动态库缺失、无法加载或 ABI 版本不一致时，
 * Python 侧会自动回退到纯 Python 实现。修改本头文件时请同步
 * flint/infra/native_loader.py；任何破坏性变更都要提升
 * FLINT_NATIVE_ABI_VERSION（参见 native/README.md）。
 *
 * 所有 ``const char *`` 路径均为 UTF-8 编码。全部函数线程安全；
 * 错误文本按线程独立保存。
 */

#ifndef FLINT_NATIVE_H
#define FLINT_NATIVE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * 符号可见性：包含本头文件的调用方只会看到普通声明，
 * 只有构建动态库时（定义 FLINT_NATIVE_BUILD）才导出符号。
 */
#if defined(_WIN32)
#if defined(FLINT_NATIVE_BUILD)
#define FLINT_API __declspec(dllexport)
#else
#define FLINT_API
#endif
#elif defined(__GNUC__) && __GNUC__ >= 4
#define FLINT_API __attribute__((visibility("default")))
#else
#define FLINT_API
#endif

/* flint_abi_version() 返回的 ABI 版本，必须与 native_loader.py 保持一致。 */
#define FLINT_NATIVE_ABI_VERSION 1

/* 状态码（均为负数，FLINT_OK 表示成功）。 */
#define FLINT_OK 0
#define FLINT_ERR_INVALID_ARG (-1)
#define FLINT_ERR_IO (-2)
#define FLINT_ERR_UNSUPPORTED (-3)
#define FLINT_ERR_CANCELLED (-4)
#define FLINT_ERR_ZIP (-5)
#define FLINT_ERR_ABI (-6)
#define FLINT_ERR_PATH_TRAVERSAL (-7)
#define FLINT_ERR_NOT_FOUND (-8)

/* 十六进制摘要所需的缓冲区大小，含结尾的 NUL。 */
#define FLINT_HASH_HEX_SIZE 65

/*
 * 取消回调：返回非零即中止当前操作。
 * 回调由执行该操作的线程调用，因此必须足够轻量，且不得在 Python 侧抛异常。
 */
typedef int (*flint_cancel_fn)(void *user_data);

/* 返回 FLINT_NATIVE_ABI_VERSION。 */
FLINT_API int flint_abi_version(void);

/* 返回调用线程最近一次的错误信息（永不为 NULL）。 */
FLINT_API const char *flint_last_error(void);

/* 清除当前线程的错误信息。 */
FLINT_API void flint_clear_error(void);

/*
 * 计算文件哈希。
 *   path     - 普通文件的 UTF-8 路径
 *   algo     - "sha1" 或 "sha256"（不区分大小写）
 *   out_hex  - 输出缓冲区，至少 FLINT_HASH_HEX_SIZE 字节
 *   out_len  - out_hex 的字节长度
 * 写入小写十六进制摘要并追加 NUL。返回 FLINT_OK 或错误码。
 */
FLINT_API int flint_hash_file(const char *path, const char *algo, char *out_hex, size_t out_len);

/*
 * 以 1 MiB 为单位复制文件。目标文件会先被截断；
 * 原子替换由调用方负责（先写 ``*.part`` 再重命名）。
 */
FLINT_API int flint_copy_file(const char *src, const char *dst, flint_cancel_fn cancel_fn,
                              void *user_data);

/*
 * 把 ZIP 压缩包解压到 dest_dir。
 * 任何会逃出 dest_dir 的成员（绝对路径、盘符、含 ".." 的路径分量）
 * 都会在任何写入发生之前被拒绝，并返回 FLINT_ERR_PATH_TRAVERSAL。
 */
FLINT_API int flint_extract_zip(const char *zip_path, const char *dest_dir,
                                flint_cancel_fn cancel_fn, void *user_data);

#ifdef __cplusplus
} /* extern "C" 结束 */
#endif

#endif /* FLINT_NATIVE_H */
