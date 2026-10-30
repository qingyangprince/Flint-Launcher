"""ZIP 解压：原生加速、Zip Slip 防护与取消支持。"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path, PurePosixPath

from flint.infra import fs, native_loader

logger = logging.getLogger(__name__)

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class ExtractionError(Exception):
    """压缩包无法安全解压时抛出。"""


class ExtractionCancelled(ExtractionError):
    """通过取消令牌中止解压时抛出。"""


def is_safe_member(name: str) -> bool:
    """``name`` 无法逃出解压根目录时返回 ``True``。"""
    if not name or "\x00" in name:
        return False
    if name.startswith(("/", "\\")) or _DRIVE_RE.match(name):
        return False

    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts:
        return False
    return all(part not in ("..", "") for part in parts)


def target_path(dest_root: Path | str, name: str) -> Path:
    """把压缩包内的成员名解析为 ``dest_root`` 内的绝对路径。"""
    root = Path(dest_root).resolve()
    if not is_safe_member(name):
        raise ExtractionError(f"unsafe archive member: {name!r}")
    candidate = (root / name.replace("\\", "/")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ExtractionError(f"archive member escapes the target directory: {name!r}")
    return candidate


def extract_zip(
    zip_path: Path | str,
    dest_dir: Path | str,
    *,
    cancel: object = None,
    use_native: bool = True,
) -> None:
    """把 ``zip_path`` 解压到 ``dest_dir``，遇到不安全路径或取消请求时抛出异常。"""
    zip_path, dest_dir = Path(zip_path), Path(dest_dir)
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)
    fs.ensure_dir(dest_dir)

    if fs.is_cancelled(cancel):
        raise ExtractionCancelled(f"extraction cancelled before start: {zip_path}")

    if use_native:
        native = native_loader.get_native()
        if native is not None:
            try:
                native.extract_zip(zip_path, dest_dir, cancel=cancel)
                return
            except native_loader.NativeCancelled as exc:
                raise ExtractionCancelled(str(exc)) from exc
            except native_loader.NativeError as exc:
                logger.debug("native extraction failed, falling back to zipfile: %s", exc)

    _extract_with_zipfile(zip_path, dest_dir, cancel)


def _extract_with_zipfile(zip_path: Path, dest_dir: Path, cancel: object) -> None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                if fs.is_cancelled(cancel):
                    raise ExtractionCancelled(f"extraction cancelled: {zip_path}")
                if info.is_dir():
                    fs.ensure_dir(target_path(dest_dir, info.filename))
                    continue
                destination = target_path(dest_dir, info.filename)
                fs.ensure_parent(destination)
                with archive.open(info) as source, destination.open("wb") as target:
                    while True:
                        if fs.is_cancelled(cancel):
                            raise ExtractionCancelled(f"extraction cancelled: {zip_path}")
                        chunk = source.read(fs.COPY_BUFFER_SIZE)
                        if not chunk:
                            break
                        target.write(chunk)
    except (ExtractionError, ExtractionCancelled):
        raise
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"invalid zip archive: {zip_path}: {exc}") from exc
    except OSError as exc:
        raise ExtractionError(f"failed to extract {zip_path}: {exc}") from exc


def extract_member(zip_path: Path | str, member: str, dest_dir: Path | str) -> Path:
    """解压单个成员并返回写入的路径。"""
    zip_path, dest_dir = Path(zip_path), Path(dest_dir)
    destination = target_path(dest_dir, member)
    fs.ensure_parent(destination)
    with (
        zipfile.ZipFile(zip_path) as archive,
        archive.open(member) as source,
        destination.open("wb") as target,
    ):
        while True:
            chunk = source.read(fs.COPY_BUFFER_SIZE)
            if not chunk:
                break
            target.write(chunk)
    return destination


def list_members(zip_path: Path | str) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        return archive.namelist()
