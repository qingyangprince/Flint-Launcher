"""文件/字节哈希：优先走原生实现，失败时回退 ``hashlib``。"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, BinaryIO

from flint.infra import native_loader

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024

_ALGOS = {"sha1": "sha1", "sha256": "sha256"}


def normalize_algo(algo: str) -> str:
    """把用户传入的算法名（``SHA-1``、``sha256``…）映射为 hashlib 的算法名。"""
    key = str(algo).strip().lower().replace("-", "")
    try:
        return _ALGOS[key]
    except KeyError:
        raise ValueError(f"unsupported hash algorithm: {algo!r}") from None


def hash_bytes(data: bytes | bytearray | memoryview, algo: str = "sha1") -> str:
    """返回 ``data`` 的小写十六进制摘要。"""
    digest = hashlib.new(normalize_algo(algo))
    digest.update(data)
    return digest.hexdigest()


def hash_file(
    path: Path | str,
    algo: str = "sha1",
    *,
    chunk_size: int = CHUNK_SIZE,
    use_native: bool = True,
) -> str:
    """分块流式读取文件，返回其小写十六进制摘要。"""
    path = Path(path)
    canonical = normalize_algo(algo)
    if not path.is_file():
        raise FileNotFoundError(path)

    if use_native:
        native = native_loader.get_native()
        if native is not None:
            try:
                return native.hash_file(path, canonical)
            except native_loader.NativeError as exc:
                logger.debug("native hash failed, falling back to hashlib: %s", exc)

    digest = hashlib.new(canonical)
    with path.open("rb") as handle:
        _update_from_stream(digest, handle, chunk_size)
    return digest.hexdigest()


def hash_stream(handle: BinaryIO, algo: str = "sha1", *, chunk_size: int = CHUNK_SIZE) -> str:
    """返回已打开的二进制流的十六进制摘要。"""
    digest = hashlib.new(normalize_algo(algo))
    _update_from_stream(digest, handle, chunk_size)
    return digest.hexdigest()


def verify_file(
    path: Path | str,
    expected: str,
    algo: str = "sha1",
    *,
    chunk_size: int = CHUNK_SIZE,
    use_native: bool = True,
) -> bool:
    """文件存在且与 ``expected`` 一致（不区分大小写）时返回 ``True``。"""
    if not expected:
        return False
    path = Path(path)
    if not path.is_file():
        return False
    actual = hash_file(path, algo, chunk_size=chunk_size, use_native=use_native)
    return actual.lower() == expected.strip().lower()


def _update_from_stream(digest: Any, handle: BinaryIO, chunk_size: int) -> None:
    while True:
        chunk = handle.read(chunk_size)
        if not chunk:
            break
        digest.update(chunk)
