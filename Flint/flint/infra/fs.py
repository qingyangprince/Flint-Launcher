"""文件系统基础操作：原子写、复制与安全删除。"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from flint.infra import native_loader

logger = logging.getLogger(__name__)

COPY_BUFFER_SIZE = 1024 * 1024


class FileOperationError(Exception):
    """文件系统操作失败时抛出。"""


class OperationCancelled(FileOperationError):
    """取消令牌要求中止时抛出。"""


def is_cancelled(cancel: object) -> bool:
    """判断 ``cancel``（Event、可调用对象或 None）是否要求中止。"""
    if cancel is None:
        return False
    if callable(cancel):
        return bool(cancel())
    checker = getattr(cancel, "is_set", None)
    if callable(checker):
        return bool(checker())
    raise TypeError(f"unsupported cancellation token: {cancel!r}")


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> Path:
    return ensure_dir(Path(path).parent)


def write_atomic(path: Path, data: bytes | str, *, encoding: str = "utf-8") -> Path:
    """把 ``data`` 先写入临时文件，再原子重命名到 ``path``。"""
    path = Path(path)
    ensure_parent(path)
    payload = data.encode(encoding) if isinstance(data, str) else bytes(data)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return path


def copy_file(
    src: Path,
    dst: Path,
    *,
    cancel: object = None,
    use_native: bool = True,
    chunk_size: int = COPY_BUFFER_SIZE,
) -> int:
    """把 ``src`` 复制到 ``dst``，返回写入的字节数。"""
    src, dst = Path(src), Path(dst)
    if not src.is_file():
        raise FileNotFoundError(src)
    ensure_parent(dst)

    if is_cancelled(cancel):
        raise OperationCancelled(f"copy cancelled: {src} -> {dst}")

    if use_native:
        native = native_loader.get_native()
        if native is not None:
            try:
                native.copy_file(src, dst, cancel=cancel)
                return dst.stat().st_size
            except native_loader.NativeCancelled as exc:
                raise OperationCancelled(str(exc)) from exc
            except native_loader.NativeError as exc:
                logger.debug("native copy failed, falling back to Python: %s", exc)

    written = 0
    try:
        with src.open("rb") as source, dst.open("wb") as target:
            while True:
                if is_cancelled(cancel):
                    raise OperationCancelled(f"copy cancelled: {src} -> {dst}")
                chunk = source.read(chunk_size)
                if not chunk:
                    break
                target.write(chunk)
                written += len(chunk)
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return written


def copy_tree(src: Path, dst: Path, *, cancel: object = None) -> None:
    """递归复制 ``src`` 到 ``dst``（合并写入），并遵循 ``cancel``。"""
    src, dst = Path(src), Path(dst)
    if not src.is_dir():
        raise FileNotFoundError(src)
    for root, _dirs, files in os.walk(src):
        if is_cancelled(cancel):
            raise OperationCancelled(f"copy cancelled: {src} -> {dst}")
        rel = Path(root).relative_to(src)
        ensure_dir(dst / rel)
        for name in files:
            copy_file(Path(root) / name, dst / rel / name, cancel=cancel)


def move(src: Path, dst: Path) -> Path:
    """移动文件或目录，目标已存在的同名文件会被替换。"""
    src, dst = Path(src), Path(dst)
    ensure_parent(dst)
    if dst.is_dir() and not src.is_dir():
        raise IsADirectoryError(dst)
    if dst.exists() and not dst.is_dir():
        dst.unlink()
    shutil.move(str(src), str(dst))
    return dst


def remove(path: Path, *, missing_ok: bool = True) -> None:
    """删除文件或整棵目录树。"""
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        if missing_ok:
            return
        raise FileNotFoundError(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def file_size(path: Path) -> int:
    return Path(path).stat().st_size


def read_bytes(path: Path) -> bytes:
    return Path(path).read_bytes()


def read_text(path: Path, *, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)
