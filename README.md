# Flint

Flint 是一个面向 Minecraft: Java Edition 的启动器：界面使用 PySide6，核心逻辑为纯 Python，
性能敏感的哈希 / 解压 / 大文件复制由可选的 C++17 动态库 `flint_native` 加速，库缺失或 ABI
不匹配时自动回退到纯 Python 实现。

## 当前进度（P0）

P0 目标：**打通版本解析与下载**，并**打通 Python ↔ C++**。

| 模块 | 状态 | 说明 |
|---|---|---|
| `flint/core/config.py` | ✅ | TOML 配置读写、默认值兜底、校验、变更事件 |
| `flint/core/events.py` | ✅ | 线程安全事件总线（进度 / 日志 / 任务 / 状态） |
| `flint/core/version.py` | ✅ | manifest 拉取、`inheritsFrom` 继承链合并、`rules` 过滤 |
| `flint/infra/http.py` | ✅ | 统一 httpx 客户端（超时 / 代理 / UA / 指数退避重试） |
| `flint/infra/cache.py` | ✅ | ETag / Last-Modified 条件请求缓存 |
| `flint/infra/downloader.py` | ✅ | 并发下载、断点续传、镜像切换、重试、SHA-1 校验 |
| `flint/infra/native_loader.py` | ✅ | 动态库定位 / 加载 / ABI 校验 / 回退 |
| `flint/infra/hash.py` / `extract.py` / `fs.py` | ✅ | 原生优先、纯 Python 兜底 |
| `flint/native/` | ✅ | `hash` / `unzip` / `fs` / `abort` / `version` + CMake |

UI（`flint/ui/`）、实例与账户、启动编排属于 P1/P2，尚未实现。

## 目录结构

```
flint/
├── core/      # 应用服务层（配置、版本、实例、账户、启动……）
├── infra/     # 基础设施层（HTTP、下载、哈希、解压、进程……）
├── platform/  # 平台适配层（路径、Java、进程、权限）
├── native/    # C++17 源码 + CMake 构建
└── lib/       # 运行时动态库产物（构建后生成，已 gitignore）
tests/         # pytest + pytest-asyncio + respx
```

依赖方向：`ui → core → infra → platform`，`infra/native_loader` 是唯一接触 C++ 的入口。

## 环境要求

* Python ≥ 3.11
* C++17 编译器（MSVC / g++ / clang++）与 CMake ≥ 3.18 —— 仅构建原生加速库时需要

## 开发

```bash
python -m pip install -e ".[dev]"

# 构建 C++ 加速库并放入 flint/lib/
cmake -S flint/native -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
cmake --build build/native --target stage

# 测试与检查
python -m pytest
python -m ruff check flint tests
```

原生库缺失时测试仍会通过，相关用例自动跳过；构建后原生/纯 Python 两条路径都会被执行。

## 使用（库方式）

```python
import asyncio
from flint.core.version import VersionResolver

async def main() -> None:
    resolver = VersionResolver()
    version = await resolver.resolve("1.20.1")
    print(version.id, version.main_class, len(version.libraries))

asyncio.run(main())
```

## 许可

Flint 以 GNU General Public License v3.0 或更高版本发布，见 [LICENSE](LICENSE)。
