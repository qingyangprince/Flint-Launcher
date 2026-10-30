/*
 * 预留：未来的 pybind11 绑定模块。
 *
 * 当前集成方式是通过 ctypes 调用 include/flint_native.h 中的稳定 C ABI
 * （见 flint/infra/native_loader.py），本文件刻意不参与 CMake 构建。
 * 将来如需迁移：
 *
 *   1. 把 pybind11 加为构建依赖；
 *   2. 新增 `pybind11_add_module(flint_native_py bindings/pybind11_module.cpp)`
 *      目标并链接同一批源文件；
 *   3. 保留 C ABI 导出，使迁移期间 ctypes 通道仍可正常工作。
 */

#if 0
#include <pybind11/pybind11.h>

PYBIND11_MODULE(flint_native_py, m) {
    m.doc() = "Flint 原生辅助函数（预留）";
}
#endif
