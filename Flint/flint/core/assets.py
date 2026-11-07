"""assets index 解析、对象下载计划与缺失校验。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flint.platform import paths

logger = logging.getLogger(__name__)

RESOURCES_BASE = "https://resources.download.minecraft.net/"
BMCLAPI_RESOURCES_BASE = "https://bmclapi2.bangbang93.com/assets/"


@dataclass(frozen=True)
class AssetFile:
    """一个资源对象（按哈希寻址）。"""

    name: str
    path: Path
    url: str
    sha1: str
    size: int | None = None


def assets_root(root: Path | str | None = None) -> Path:
    return Path(root) if root is not None else paths.assets_dir()


def index_path(asset_index_id: str, root: Path | str | None = None) -> Path:
    return assets_root(root) / "indexes" / f"{asset_index_id}.json"


def objects_dir(root: Path | str | None = None) -> Path:
    return assets_root(root) / "objects"


def object_path(hash_value: str, root: Path | str | None = None) -> Path:
    return objects_dir(root) / hash_value[:2] / hash_value


def parse_index(data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """返回 ``{逻辑名: {"hash": ..., "size": ...}}``。"""
    raw_objects = data.get("objects")
    if not isinstance(raw_objects, Mapping):
        logger.warning("asset index has no 'objects' mapping")
        return {}
    objects: dict[str, dict[str, Any]] = {}
    for name, entry in raw_objects.items():
        if not isinstance(entry, Mapping):
            continue
        hash_value = entry.get("hash")
        if not isinstance(hash_value, str) or len(hash_value) < 2:
            continue
        objects[str(name)] = {
            "hash": hash_value,
            "size": int(entry["size"]) if entry.get("size") is not None else None,
        }
    return objects


def build_asset_files(
    objects: Mapping[str, Mapping[str, Any]],
    *,
    root: Path | str | None = None,
    mirror: str = "official",
) -> list[AssetFile]:
    files: list[AssetFile] = []
    for name, entry in objects.items():
        hash_value = str(entry["hash"])
        official = f"{RESOURCES_BASE}{hash_value[:2]}/{hash_value}"
        url = f"{BMCLAPI_RESOURCES_BASE}{hash_value[:2]}/{hash_value}" if mirror == "bmclapi" else official
        files.append(
            AssetFile(
                name=name,
                path=object_path(hash_value, root),
                url=url,
                sha1=hash_value,
                size=int(entry["size"]) if entry.get("size") is not None else None,
            )
        )
    return files


def missing_assets(files: list[AssetFile]) -> list[AssetFile]:
    missing: list[AssetFile] = []
    for item in files:
        try:
            if not item.path.is_file() or (
                item.size is not None and item.path.stat().st_size != item.size
            ):
                missing.append(item)
        except OSError:
            missing.append(item)
    return missing
