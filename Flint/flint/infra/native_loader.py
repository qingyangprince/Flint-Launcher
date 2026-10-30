"""可选 C++ 辅助库（``flint_native``）的加载器。

查找顺序：

1. ``FLINT_NATIVE_LIB`` —— 直接指定动态库路径
2. ``FLINT_NATIVE_DIR`` —— 包含平台动态库的目录
3. ``flint/lib/`` —— 包内随发行版分发的目录
4. 系统加载器（``ctypes.util.find_library``）

只有当库导出了 ``flint_abi_version`` 且返回值与 :data:`FLINT_NATIVE_ABI_VERSION`
一致时才会被采用。任何失败都不会中断程序：调用方从 :func:`get_native` 收到
``None``，转而使用纯 Python 实现。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from flint.platform import paths

logger = logging.getLogger(__name__)

FLINT_NATIVE_ABI_VERSION = 1

FLINT_OK = 0
FLINT_ERR_INVALID_ARG = -1
FLINT_ERR_IO = -2
FLINT_ERR_UNSUPPORTED = -3
FLINT_ERR_CANCELLED = -4
FLINT_ERR_ZIP = -5
FLINT_ERR_ABI = -6
FLINT_ERR_PATH_TRAVERSAL = -7
FLINT_ERR_NOT_FOUND = -8

HASH_HEX_SIZE = 65

_CANCEL_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
_NULL_CANCEL = _CANCEL_FN()

_LIBRARY_NAMES = {
    "win32": ("flint_native.dll", "libflint_native.dll"),
    "darwin": ("libflint_native.dylib", "flint_native.dylib"),
    "linux": ("libflint_native.so", "flint_native.so"),
}

_CANCEL_CODES = {FLINT_ERR_CANCELLED}


class NativeError(Exception):
    """原生库所有失败的基类。"""


class NativeUnavailable(NativeError):
    """动态库缺失、无法加载或 ABI 不兼容。"""


class NativeCallError(NativeError):
    """原生函数返回了非零状态码。"""

    def __init__(self, message: str, *, code: int, function: str) -> None:
        super().__init__(message)
        self.code = code
        self.function = function


class NativeCancelled(NativeCallError):
    """调用方请求取消，原生调用被中止。"""


def _library_names() -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return _LIBRARY_NAMES["win32"]
    if sys.platform == "darwin":
        return _LIBRARY_NAMES["darwin"]
    return _LIBRARY_NAMES["linux"]


def _candidate_paths() -> Iterator[Path]:
    seen: set[str] = set()

    def emit(path: Path | str | None) -> Iterator[Path]:
        if not path:
            return
        candidate = Path(path)
        key = str(candidate).lower() if os.name == "nt" else str(candidate)
        if key in seen:
            return
        seen.add(key)
        yield candidate

    explicit = os.environ.get("FLINT_NATIVE_LIB")
    if explicit:
        yield from emit(explicit)

    directories = [os.environ.get("FLINT_NATIVE_DIR"), paths.natives_lib_dir()]
    for directory in directories:
        if not directory:
            continue
        for name in _library_names():
            yield from emit(Path(directory) / name)

    located = ctypes.util.find_library("flint_native")
    if located:
        yield from emit(located)


def _bind(library: ctypes.CDLL) -> ctypes.CDLL:
    library.flint_abi_version.argtypes = []
    library.flint_abi_version.restype = ctypes.c_int
    library.flint_last_error.argtypes = []
    library.flint_last_error.restype = ctypes.c_char_p
    library.flint_clear_error.argtypes = []
    library.flint_clear_error.restype = None
    library.flint_hash_file.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    library.flint_hash_file.restype = ctypes.c_int
    library.flint_copy_file.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        _CANCEL_FN,
        ctypes.c_void_p,
    ]
    library.flint_copy_file.restype = ctypes.c_int
    library.flint_extract_zip.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        _CANCEL_FN,
        ctypes.c_void_p,
    ]
    library.flint_extract_zip.restype = ctypes.c_int
    return library


def _encode_path(path: Path | str) -> bytes:
    return os.fspath(path).encode("utf-8")


def _cancel_bridge(cancel: object) -> tuple[_CANCEL_FN, ctypes.c_void_p | None, object]:
    """把 Python 取消令牌适配为 C 回调，并保证回调对象在整个调用期间存活。"""
    if cancel is None:
        return _NULL_CANCEL, None, None

    if callable(cancel):
        predicate: Callable[[], bool] = cancel
    else:
        checker = getattr(cancel, "is_set", None)
        if not callable(checker):
            raise TypeError(f"unsupported cancellation token: {cancel!r}")
        predicate = checker

    callback = _CANCEL_FN(lambda _user_data: 1 if predicate() else 0)
    return callback, None, callback


class NativeLibrary:
    """对导出的 C ABI 的轻量类型化封装。"""

    def __init__(self, path: Path | str, library: ctypes.CDLL, abi_version: int) -> None:
        self._path = Path(path)
        self._lib = library
        self.abi_version = abi_version

    @property
    def path(self) -> Path:
        return self._path

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"NativeLibrary(path={self._path!r}, abi={self.abi_version})"

    def last_error(self) -> str:
        raw = self._lib.flint_last_error()
        return raw.decode("utf-8", "replace") if raw else ""

    def _check(self, code: int, function: str, *, action: str) -> None:
        if code == FLINT_OK:
            return
        message = self.last_error() or f"{function} failed with code {code}"
        error_type = NativeCancelled if code in _CANCEL_CODES else NativeCallError
        raise error_type(f"{action}: {message} (code {code})", code=code, function=function)

    def hash_file(self, path: Path | str, algo: str = "sha1") -> str:
        buffer = ctypes.create_string_buffer(HASH_HEX_SIZE)
        code = self._lib.flint_hash_file(
            _encode_path(path), algo.encode("ascii"), buffer, ctypes.c_size_t(HASH_HEX_SIZE)
        )
        self._check(code, "flint_hash_file", action=f"hashing {path}")
        return buffer.value.decode("ascii")

    def copy_file(self, src: Path | str, dst: Path | str, *, cancel: object = None) -> None:
        callback, user_data, _keepalive = _cancel_bridge(cancel)
        code = self._lib.flint_copy_file(_encode_path(src), _encode_path(dst), callback, user_data)
        self._check(code, "flint_copy_file", action=f"copying {src} -> {dst}")

    def extract_zip(
        self, zip_path: Path | str, dest_dir: Path | str, *, cancel: object = None
    ) -> None:
        callback, user_data, _keepalive = _cancel_bridge(cancel)
        code = self._lib.flint_extract_zip(
            _encode_path(zip_path), _encode_path(dest_dir), callback, user_data
        )
        self._check(code, "flint_extract_zip", action=f"extracting {zip_path}")


_lock = threading.RLock()
_cached: NativeLibrary | None = None
_attempted = False
_unavailable_reason: str | None = None


def _load_library(path: Path) -> NativeLibrary:
    try:
        raw = ctypes.CDLL(str(path))
    except OSError as exc:
        raise NativeUnavailable(f"cannot load {path}: {exc}") from exc

    try:
        library = _bind(raw)
        abi = int(library.flint_abi_version())
    except AttributeError as exc:
        raise NativeUnavailable(f"{path} does not export the Flint ABI: {exc}") from exc
    except OSError as exc:
        raise NativeUnavailable(f"{path} failed to initialise: {exc}") from exc

    if abi != FLINT_NATIVE_ABI_VERSION:
        raise NativeUnavailable(
            f"ABI mismatch for {path}: library reports {abi}, expected {FLINT_NATIVE_ABI_VERSION}"
        )
    return NativeLibrary(path, library, abi)


def get_native(*, refresh: bool = False) -> NativeLibrary | None:
    """返回已加载的原生库；无法使用时返回 ``None``。"""
    global _cached, _attempted, _unavailable_reason

    with _lock:
        if _attempted and not refresh:
            return _cached

        _attempted = True
        _cached = None
        _unavailable_reason = None
        errors: list[str] = []

        for candidate in _candidate_paths():
            try:
                exists = candidate.exists()
            except OSError:
                exists = False
            if not exists and not _is_system_path(candidate):
                continue
            try:
                library = _load_library(candidate)
            except NativeUnavailable as exc:
                errors.append(str(exc))
                logger.debug("native library rejected: %s", exc)
                continue
            except Exception as exc:  # pragma: no cover - 兜底，防止加载过程抛出意外异常
                errors.append(f"{candidate}: {exc}")
                logger.debug("unexpected native load failure for %s", candidate, exc_info=True)
                continue

            _cached = library
            _unavailable_reason = None
            logger.info("loaded native library %s (ABI %d)", library.path, library.abi_version)
            return _cached

        _unavailable_reason = "; ".join(errors) if errors else "no flint_native library found"
        logger.debug("native library unavailable: %s", _unavailable_reason)
        return None


def _is_system_path(path: Path) -> bool:
    return not path.is_absolute()


def is_available() -> bool:
    return get_native() is not None


def unavailable_reason() -> str | None:
    """最近一次查找失败的可读原因（成功加载时为 ``None``）。"""
    get_native()
    return _unavailable_reason


def reset_cache() -> None:
    """丢弃上一次的查找结果（测试和新构建产物放入 ``flint/lib/`` 后使用）。"""
    global _cached, _attempted, _unavailable_reason
    with _lock:
        _cached = None
        _attempted = False
        _unavailable_reason = None
