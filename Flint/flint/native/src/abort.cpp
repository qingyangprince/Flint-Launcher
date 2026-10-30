/* 线程级错误上报与取消辅助。 */

#include "flint_internal.h"

namespace {

std::string &error_buffer() {
    thread_local std::string value;
    return value;
}

} // namespace

namespace flint {

void set_error(const std::string &message) { error_buffer() = message; }

void clear_error() { error_buffer().clear(); }

bool cancelled(flint_cancel_fn cancel_fn, void *user_data) {
    if (cancel_fn == nullptr) {
        return false;
    }
    return cancel_fn(user_data) != 0;
}

} // namespace flint

extern "C" const char *flint_last_error(void) { return error_buffer().c_str(); }

extern "C" void flint_clear_error(void) { error_buffer().clear(); }
