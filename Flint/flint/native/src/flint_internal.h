/*
 * 各编译单元共用的内部辅助声明。本头文件不属于公开 ABI，
 * 不得安装，也不应被调用方包含。
 */

#ifndef FLINT_INTERNAL_H
#define FLINT_INTERNAL_H

#include <cstdio>
#include <string>

#include "flint_native.h"

namespace flint {

/* 写入/替换 flint_last_error() 返回的线程级错误信息。 */
void set_error(const std::string &message);
void clear_error();

/* 调用取消回调，并避免解引用空指针。 */
bool cancelled(flint_cancel_fn cancel_fn, void *user_data);

/* fopen() 包装：在各平台都接受 UTF-8 路径。 */
std::FILE *open_file(const char *path, const char *mode);

} // namespace flint

#endif /* FLINT_INTERNAL_H */
