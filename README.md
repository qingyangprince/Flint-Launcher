# Flint

Flint 是一个面向 Minecraft: Java Edition 的启动器：界面使用 PySide6，核心逻辑为纯 Python，
性能敏感的哈希 / 解压 / 大文件复制由可选的 C++17 动态库 `flint_native` 加速，库缺失或 ABI
不匹配时自动回退到纯 Python 实现。

## 当前进度（P2）

P2 目标：**第一个可用界面**——实例与账户、启动编排、前后端桥接。

| 模块 | 状态 | 说明 |
|---|---|---|
| `flint/core/config.py` | ✅ | TOML 配置读写、默认值兜底、校验、变更事件 |
| `flint/core/events.py` | ✅ | 线程安全事件总线（进度 / 日志 / 任务 / 状态） |
| `flint/core/version.py` | ✅ | manifest 拉取、`inheritsFrom` 继承链合并、`rules` 过滤 |
| `flint/core/instance.py` | ✅ | 实例元数据 JSON、CRUD、复制、zip 导入导出、选择事件 |
| `flint/core/account.py` | ✅ | 微软设备码 OAuth（Xbox→XSTS→MC）、离线 UUID、token 加密持久化 |
| `flint/core/libraries.py` | ✅ | libraries / natives 下载计划、classpath 组装 |
| `flint/core/assets.py` | ✅ | assets index 解析、对象下载计划与缺失校验 |
| `flint/core/launcher.py` | ✅ | 版本解析、文件补齐、JVM/游戏参数拼装、进程拉起 |
| `flint/infra/http.py` | ✅ | 统一 httpx 客户端（超时 / 代理 / UA / 指数退避重试） |
| `flint/infra/cache.py` | ✅ | ETag / Last-Modified 条件请求缓存 |
| `flint/infra/downloader.py` | ✅ | 并发下载、断点续传、镜像切换、重试、SHA-1 校验 |
| `flint/infra/process.py` | ✅ | 无窗口子进程、stdout/stderr 逐行回调、进程树终止 |
| `flint/infra/native_loader.py` | ✅ | 动态库定位 / 加载 / ABI 校验 / 回退 |
| `flint/infra/hash.py` / `extract.py` / `fs.py` | ✅ | 原生优先、纯 Python 兜底 |
| `flint/platform/java.py` | ✅ | 三平台 JRE 探测、`java -version` 解析、版本推荐 |
| `flint/native/` | ✅ | `hash` / `unzip` / `fs` / `abort` / `version` + CMake |
| `flint/ui/state.py` | ✅ | 当前实例 / 账户 / 进程状态，启动与停止编排 |
| `flint/ui/bridge.py` | ✅ | 事件总线 → Qt Signal，协程 → 后台事件循环 |
| `flint/ui/pages/launch/*` | ✅ | 实例列表（右键编辑/复制/删除/打开目录）+ 启动右栏 |
| `flint/ui/views/launch_panel.py` | ✅ | 账户行、大启动按钮、内存滑块、Java 选择、最近日志 |
| `flint/ui/overlay.py` | ✅ | 内容区遮罩确认框（替代 `QMessageBox`） |
| `flint/ui/main_window.py` | ✅ | 四标签 + 左右分栏 + HintBar，接入状态与启动流程 |

下载页、设置页表单、工具页各视图（安装 / 模组 / 账户 / 日志面板）与 `build/`、CI 属于 P3。

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

# 可选：启用账户 token 的加密存储（Fernet/AES）。
# 未安装时账户库退化为编码存储并写一条告警日志。
python -m pip install -e ".[secure]"

# 构建 C++ 加速库并放入 flint/lib/
cmake -S flint/native -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
cmake --build build/native --target stage

# 测试与检查
python -m pytest
python -m ruff check flint tests
```

原生库缺失时测试仍会通过，相关用例自动跳过；构建后原生/纯 Python 两条路径都会被执行。

## 运行

项目根为 `Flint/`（`flint` 包位于其中），运行前需先切换到该目录：

```bash
cd Flint
python -m flint               # 启动图形界面（主入口）
python -m flint --version     # 打印版本号
python -m flint --debug       # 开启 DEBUG 日志

# 也可以直接运行主窗口模块（同样需在 Flint/ 目录下）
python -m flint.ui.main_window
```

## 使用（库方式）

```python
import asyncio

from flint.core.account import AccountManager
from flint.core.instance import InstanceManager
from flint.core.launcher import Launcher


async def main() -> None:
    instances = InstanceManager()
    instance = instances.create("1.20.1 原版", "1.20.1")

    accounts = AccountManager()
    accounts.load()
    account = accounts.add_offline("Steve")

    launcher = Launcher(instances_root=instances.root)
    plan, process = await launcher.launch(instance, account)
    print(plan.display_command)
    print("exit code:", await process.wait())


asyncio.run(main())
```

首次启动会自动补齐客户端 jar、libraries 与 assets（受 `download.mirror` 配置影响）。

## 许可

Flint 以 GNU General Public License v3.0 或更高版本发布，见 [LICENSE](LICENSE)。
