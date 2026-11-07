"""libraries 下载计划、natives 分类与 classpath 组装。"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from flint.core.version import ResolvedVersion, current_os
from flint.platform import paths

logger = logging.getLogger(__name__)

LIBRARIES_BASE = "https://libraries.minecraft.net/"
BMCLAPI_MAVEN_BASE = "https://bmclapi2.bangbang93.com/maven/"


@dataclass(frozen=True)
class LibraryFile:
    """一个 library 文件的下载与落盘信息。"""

    name: str
    path: Path
    url: str = ""
    sha1: str | None = None
    size: int | None = None
    native: bool = False
    extract: tuple[str, ...] = ()


def maven_path(name: str) -> PurePosixPath:
    """把 Maven 坐标转换为仓库内相对路径。

    支持 ``group:artifact:version[:classifier][@ext]``。
    """
    extension = "jar"
    if "@" in name:
        name, extension = name.rsplit("@", 1)
    parts = name.split(":")
    if len(parts) < 3:
        raise ValueError(f"invalid maven coordinate: {name!r}")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = f"-{parts[3]}" if len(parts) > 3 and parts[3] else ""
    file_name = f"{artifact}-{version}{classifier}.{extension}"
    return PurePosixPath(group.replace(".", "/")) / artifact / version / file_name


def _artifact_entry(library: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    downloads = library.get("downloads")
    if not isinstance(downloads, Mapping):
        return None
    if key == "artifact":
        entry = downloads.get("artifact")
        return entry if isinstance(entry, Mapping) else None
    classifiers = downloads.get("classifiers")
    if isinstance(classifiers, Mapping):
        entry = classifiers.get(key)
        return entry if isinstance(entry, Mapping) else None
    return None


def _remote_url(
    entry: Mapping[str, Any] | None, relative: PurePosixPath, mirror: str
) -> tuple[str, str]:
    """返回 (首选 URL, 备用 URL)。``mirror`` 只影响 Maven 路径。"""
    official = f"{LIBRARIES_BASE}{relative.as_posix()}"
    mirrored = f"{BMCLAPI_MAVEN_BASE}{relative.as_posix()}"
    if entry is not None and isinstance(entry.get("url"), str) and entry["url"]:
        official = str(entry["url"])
        if official.startswith(LIBRARIES_BASE):
            mirrored = official.replace(LIBRARIES_BASE, BMCLAPI_MAVEN_BASE)
        else:
            mirrored = ""
    if mirror == "bmclapi":
        return (mirrored or official), official
    return official, mirrored


def build_library_files(
    version: ResolvedVersion,
    *,
    root: Path | str | None = None,
    mirror: str = "official",
    os_name: str | None = None,
) -> list[LibraryFile]:
    """把（已按 rules 过滤的）libraries 转成下载/classpath 计划。"""
    libraries_root = Path(root) if root is not None else paths.libraries_dir()
    platform_name = os_name or current_os()
    files: list[LibraryFile] = []

    for library in version.libraries:
        if not isinstance(library, Mapping):
            continue
        name = library.get("name")
        if not isinstance(name, str) or not name:
            continue

        natives = library.get("natives")
        classifier_key: str | None = None
        if isinstance(natives, Mapping):
            candidate = natives.get(platform_name)
            if isinstance(candidate, str) and candidate:
                classifier_key = candidate.replace("${arch}", _arch_bits())

        parts = name.split(":")
        inline_classifier = parts[3] if len(parts) > 3 else ""
        inline_native = inline_classifier.startswith("natives")
        main_entry = _artifact_entry(library, "artifact")
        extract_rules = library.get("extract")
        excludes: tuple[str, ...] = ()
        if isinstance(extract_rules, Mapping):
            raw_excludes = extract_rules.get("exclude")
            if isinstance(raw_excludes, Sequence) and not isinstance(raw_excludes, str):
                excludes = tuple(str(item) for item in raw_excludes)

        if classifier_key:
            if main_entry is not None:
                try:
                    append_file(
                        files,
                        name,
                        _entry_path(main_entry, name),
                        main_entry,
                        libraries_root,
                        mirror,
                        native=False,
                        excludes=excludes,
                    )
                except ValueError:
                    logger.debug("skipping library with invalid name: %r", name)
            try:
                classifier_entry = _artifact_entry(library, classifier_key)
                append_file(
                    files,
                    name,
                    maven_path(f"{name}:{classifier_key}"),
                    classifier_entry,
                    libraries_root,
                    mirror,
                    native=True,
                    excludes=excludes,
                )
            except ValueError:
                logger.debug("skipping native library with invalid name: %r", name)
        elif inline_native:
            append_file(
                files,
                name,
                _entry_path(main_entry, name),
                main_entry,
                libraries_root,
                mirror,
                native=True,
                excludes=excludes,
            )
        else:
            append_file(
                files,
                name,
                _entry_path(main_entry, name),
                main_entry,
                libraries_root,
                mirror,
                native=False,
                excludes=excludes,
            )
    return files


def append_file(
    files: list[LibraryFile],
    name: str,
    relative: PurePosixPath,
    entry: Mapping[str, Any] | None,
    libraries_root: Path,
    mirror: str,
    *,
    native: bool,
    excludes: tuple[str, ...],
) -> None:
    url, _fallback = _remote_url(entry, relative, mirror)
    files.append(
        LibraryFile(
            name=name,
            path=libraries_root / relative,
            url=url,
            sha1=str(entry["sha1"]) if entry is not None and entry.get("sha1") else None,
            size=int(entry["size"]) if entry is not None and entry.get("size") else None,
            native=native,
            extract=(excludes or ("META-INF/",)) if native else (),
        )
    )


def _entry_path(entry: Mapping[str, Any] | None, name: str) -> PurePosixPath:
    if entry is not None and entry.get("path"):
        return PurePosixPath(str(entry["path"]))
    return maven_path(name)


def _arch_bits() -> str:
    import platform as _platform

    machine = _platform.machine().lower()
    return "64" if machine in {"x86_64", "amd64", "aarch64", "arm64"} else "32"


def classpath(files: Sequence[LibraryFile]) -> list[Path]:
    """classpath 只需要非 native 的 jar，且顺序与版本 JSON 一致。"""
    return [item.path for item in files if not item.native]


def native_files(files: Sequence[LibraryFile]) -> list[LibraryFile]:
    return [item for item in files if item.native]


def missing_files(files: Sequence[LibraryFile]) -> list[LibraryFile]:
    """按存在性与大小判断缺失文件（不计算哈希，保持启动路径轻量）。"""
    missing: list[LibraryFile] = []
    for item in files:
        try:
            if not item.path.is_file() or (
                item.size is not None and item.path.stat().st_size != item.size
            ):
                missing.append(item)
        except OSError:
            missing.append(item)
    return missing
