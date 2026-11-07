"""实例模型与 CRUD、复制、导入导出。

每个实例对应 ``<instances_dir>/<id>/`` 一个目录，元数据保存在该目录下的
``instance.json``，游戏文件（mods、saves、options.txt……）也落在同一目录，
因此实例天然互相隔离。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import zipfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flint.core import config as config_module
from flint.core import events
from flint.infra import extract, fs
from flint.platform import paths

logger = logging.getLogger(__name__)

META_FILE_NAME = "instance.json"
META_SCHEMA_VERSION = 1
MAX_NAME_LENGTH = 64
MAX_LOADER_LENGTH = 32
LOADERS = ("vanilla", "fabric", "forge", "quilt", "neoforge")
_LOADER_ALIASES = {
    "": "vanilla",
    "vanilla": "vanilla",
    "original": "vanilla",
    "原版": "vanilla",
    "fabric": "fabric",
    "forge": "forge",
    "quilt": "quilt",
    "neoforge": "neoforge",
}
_INVALID_NAME_CHARS = set('<>:"/\\|?*')
_SLUG_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")


class InstanceError(Exception):
    """实例操作失败时抛出。"""


class InstanceNotFound(InstanceError):
    """按名称或 id 找不到实例。"""


class InstanceExists(InstanceError):
    """名称已被占用。"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize_loader(loader: str | None) -> str:
    """把用户输入的加载器名规范化为 :data:`LOADERS` 中的值。"""
    key = (loader or "").strip().lower()
    normalized = _LOADER_ALIASES.get(key)
    if normalized is None:
        raise InstanceError(f"unknown loader: {loader!r}")
    return normalized


def validate_name(name: str) -> str:
    """校验实例名，返回去除首尾空白后的结果。"""
    if not isinstance(name, str):
        raise InstanceError("instance name must be a string")
    cleaned = name.strip()
    if not cleaned:
        raise InstanceError("instance name must not be empty")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise InstanceError(f"instance name must be at most {MAX_NAME_LENGTH} characters")
    if cleaned in {".", ".."} or any(ch in _INVALID_NAME_CHARS for ch in cleaned):
        raise InstanceError(f"instance name contains invalid characters: {name!r}")
    return cleaned


def validate_version(version: str) -> str:
    if not isinstance(version, str) or not version.strip():
        raise InstanceError("instance version must be a non-empty string")
    return version.strip()


def slugify(name: str) -> str:
    """把实例名转成可用作目录名的 id；保留中文与字母数字。"""
    slug = _SLUG_RE.sub("-", name.strip()).strip(".-_")
    slug = slug[:MAX_NAME_LENGTH].strip(".-_")
    return slug or "instance"


@dataclass
class Instance:
    """单个实例的元数据；游戏目录由 :class:`InstanceManager` 推导。"""

    name: str
    version: str
    loader: str = "vanilla"
    loader_version: str = ""
    id: str = ""
    memory_mb: int = config_module.DEFAULT_CONFIG["launcher.memory_mb"]
    java_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = validate_name(self.name)
        self.version = validate_version(self.version)
        self.loader = normalize_loader(self.loader)
        self.loader_version = (self.loader_version or "").strip()
        if len(self.loader_version) > MAX_LOADER_LENGTH:
            raise InstanceError(f"loader version is too long: {self.loader_version!r}")
        self.id = self.id or slugify(self.name)
        self.memory_mb = config_module.validate_value("launcher.memory_mb", self.memory_mb)
        now = _now()
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or self.created_at

    @property
    def display_loader(self) -> str:
        """给 UI 用的加载器标签，例如 ``Fabric 0.15.7``。"""
        if self.loader == "vanilla":
            return "原版"
        label = self.loader.capitalize()
        return f"{label} {self.loader_version}".strip()

    @property
    def version_id(self) -> str:
        """版本目录 id；加载器实例通常带有独立的版本 JSON。"""
        return self.extra.get("version_id") or self.version

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema"] = META_SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, fallback_id: str = "") -> Instance:
        if not isinstance(data, Mapping):
            raise InstanceError("instance metadata must be an object")
        name = data.get("name")
        version = data.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise InstanceError("instance metadata requires 'name' and 'version'")
        extra = data.get("extra")
        return cls(
            name=name,
            version=version,
            loader=str(data.get("loader", "vanilla")),
            loader_version=str(data.get("loader_version", "")),
            id=str(data.get("id") or fallback_id or slugify(name)),
            memory_mb=data.get("memory_mb", config_module.DEFAULT_CONFIG["launcher.memory_mb"]),
            java_path=str(data.get("java_path", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            extra=dict(extra) if isinstance(extra, Mapping) else {},
        )


class InstanceManager:
    """实例目录的读写入口；所有变更都会发出 ``instance_changed`` 事件。"""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        bus: events.EventBus | None = None,
    ) -> None:
        self._root = Path(root) if root is not None else paths.instances_dir()
        self._bus = bus or events.bus
        self._lock = threading.RLock()
        self._selected: Instance | None = None

    @property
    def root(self) -> Path:
        return self._root

    @property
    def selected(self) -> Instance | None:
        return self._selected

    def directory_for(self, instance: Instance | str) -> Path:
        key = instance.id if isinstance(instance, Instance) else str(instance)
        return self._root / key

    def meta_path(self, instance: Instance | str) -> Path:
        return self.directory_for(instance) / META_FILE_NAME

    def list(self) -> list[Instance]:
        """扫描实例目录，按创建时间升序返回；损坏的元数据会被跳过。"""
        if not self._root.is_dir():
            return []
        items: list[Instance] = []
        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            try:
                instance = self._read(entry)
            except InstanceError as exc:
                logger.warning("skipping unreadable instance %s: %s", entry, exc)
                continue
            if instance is not None:
                items.append(instance)
        items.sort(key=lambda item: (item.created_at, item.name.lower()))
        return items

    def get(self, key: str | Instance) -> Instance:
        """按 id 或名称（大小写不敏感）查找实例。"""
        if isinstance(key, Instance):
            key = key.id
        if not key:
            raise InstanceNotFound("empty instance key")
        key = str(key)
        if key in {".", ".."} or "/" in key or "\\" in key:
            raise InstanceNotFound(f"invalid instance key: {key!r}")
        with self._lock:
            direct = self._root / key
            if direct.is_dir():
                instance = self._read(direct)
                if instance is not None:
                    return instance
        lowered = key.lower()
        for instance in self.list():
            if instance.id.lower() == lowered or instance.name.lower() == lowered:
                return instance
        raise InstanceNotFound(f"instance not found: {key!r}")

    def exists(self, name: str) -> bool:
        try:
            self.get(name)
        except InstanceNotFound:
            return False
        return True

    def create(
        self,
        name: str,
        version: str,
        *,
        loader: str = "vanilla",
        loader_version: str = "",
        memory_mb: int | None = None,
        java_path: str = "",
        extra: Mapping[str, Any] | None = None,
    ) -> Instance:
        name = validate_name(name)
        if self._name_taken(name):
            raise InstanceExists(f"instance name already in use: {name}")
        instance = Instance(
            name=name,
            version=validate_version(version),
            loader=loader,
            loader_version=loader_version,
            memory_mb=memory_mb
            if memory_mb is not None
            else config_module.DEFAULT_CONFIG["launcher.memory_mb"],
            java_path=java_path,
            extra=dict(extra or {}),
        )
        with self._lock:
            instance.id = self._unique_id(instance.id)
            fs.ensure_dir(self.directory_for(instance))
            self._write(instance)
        self._emit("created", instance)
        return instance

    def update(self, key: str | Instance, **changes: Any) -> Instance:
        """更新实例字段；``id``、``created_at`` 不允许修改。"""
        with self._lock:
            instance = self.get(key)
            changes.pop("id", None)
            changes.pop("created_at", None)
            if "name" in changes:
                new_name = validate_name(str(changes["name"]))
                if new_name.lower() != instance.name.lower() and self._name_taken(new_name):
                    raise InstanceExists(f"instance name already in use: {new_name}")
                changes["name"] = new_name
            if "version" in changes:
                changes["version"] = validate_version(str(changes["version"]))
            if "loader" in changes:
                changes["loader"] = normalize_loader(str(changes["loader"]))
            if "memory_mb" in changes:
                changes["memory_mb"] = config_module.validate_value(
                    "launcher.memory_mb", changes["memory_mb"]
                )
            updated = replace(instance, **changes)
            updated.updated_at = _now()
            self._write(updated)
        self._emit("updated", updated)
        return updated

    def delete(self, key: str | Instance) -> None:
        with self._lock:
            instance = self.get(key)
            fs.remove(self.directory_for(instance))
            if self._selected is not None and self._selected.id == instance.id:
                self._selected = None
        self._emit("deleted", instance)

    def clone(self, key: str | Instance, new_name: str | None = None) -> Instance:
        with self._lock:
            source = self.get(key)
            name = validate_name(new_name or f"{source.name} 副本")
            if self._name_taken(name):
                raise InstanceExists(f"instance name already in use: {name}")
            copied = replace(
                source,
                name=name,
                id=self._unique_id(slugify(name)),
                created_at=_now(),
                updated_at=_now(),
            )
            target = self.directory_for(copied)
            fs.copy_tree(self.directory_for(source), target)
            self._write(copied)
        self._emit("cloned", copied)
        return copied

    def select(self, key: str | Instance | None) -> Instance | None:
        """记住当前选中的实例，并广播选择事件。"""
        instance = None if key is None else self.get(key)
        self._selected = instance
        self._emit("selected", instance)
        return instance

    def export(self, key: str | Instance, destination: Path | str) -> Path:
        """把实例目录打包为 zip（含元数据与游戏文件）。"""
        with self._lock:
            instance = self.get(key)
            directory = self.directory_for(instance)
            if not directory.is_dir():
                raise InstanceNotFound(f"instance directory is missing: {directory}")
            self._write(instance)
            destination = Path(destination)
            if destination.is_dir():
                destination = destination / f"{instance.id}.zip"
            fs.ensure_parent(destination)
            tmp = destination.with_name(destination.name + ".part")
            try:
                with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
                    for root, _dirs, files in os.walk(directory):
                        for file_name in files:
                            full = Path(root) / file_name
                            archive.write(full, full.relative_to(directory).as_posix())
                os.replace(tmp, destination)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                raise InstanceError(f"cannot export instance {instance.name!r}: {exc}") from exc
        return destination

    def import_instance(
        self,
        archive: Path | str,
        *,
        new_name: str | None = None,
        overwrite: bool = False,
    ) -> Instance:
        """从 zip 导入实例；压缩包结构须与 :meth:`export` 产出一致。"""
        archive = Path(archive)
        if not archive.is_file():
            raise InstanceError(f"instance archive not found: {archive}")

        fs.ensure_dir(self._root)
        with tempfile.TemporaryDirectory(prefix=".import-", dir=self._root) as tmp_dir:
            staging = Path(tmp_dir)
            try:
                extract.extract_zip(archive, staging)
            except (extract.ExtractionError, OSError) as exc:
                raise InstanceError(f"cannot read instance archive {archive}: {exc}") from exc

            meta_path = self._find_meta(staging)
            if meta_path is None:
                raise InstanceError(f"instance archive has no {META_FILE_NAME}: {archive}")
            instance_dir = meta_path.parent
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                instance = Instance.from_dict(data, fallback_id=slugify(instance_dir.name))
            except (OSError, ValueError, InstanceError) as exc:
                raise InstanceError(f"invalid instance metadata in {archive}: {exc}") from exc

            if new_name:
                instance.name = validate_name(new_name)
                instance.id = slugify(instance.name)

            with self._lock:
                if self._name_taken(instance.name):
                    if not overwrite:
                        raise InstanceExists(f"instance name already in use: {instance.name}")
                    self.delete(self.get(instance.name))
                instance.id = self._unique_id(instance.id)
                instance.created_at = instance.created_at or _now()
                instance.updated_at = _now()
                target = self.directory_for(instance)
                if target.exists():
                    fs.remove(target)
                os.replace(instance_dir, target)
                self._write(instance)
        self._emit("created", instance)
        return instance

    # -- internals ---------------------------------------------------------
    def _find_meta(self, root: Path) -> Path | None:
        direct = root / META_FILE_NAME
        if direct.is_file():
            return direct
        for child in sorted(root.iterdir()):
            candidate = child / META_FILE_NAME
            if child.is_dir() and candidate.is_file():
                return candidate
        return None

    def _read(self, directory: Path) -> Instance | None:
        meta = directory / META_FILE_NAME
        if not meta.is_file():
            return None
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InstanceError(f"cannot read {meta}: {exc}") from exc
        return Instance.from_dict(data, fallback_id=directory.name)

    def _write(self, instance: Instance) -> None:
        fs.write_atomic(
            self.meta_path(instance),
            json.dumps(instance.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )

    def _name_taken(self, name: str) -> bool:
        lowered = name.strip().lower()
        return any(item.name.lower() == lowered for item in self.list())

    def _unique_id(self, base: str) -> str:
        candidate = base or "instance"
        index = 2
        while (self._root / candidate).exists():
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _emit(self, action: str, instance: Instance | None) -> None:
        payload = events.InstanceChangedEvent(
            action=action,
            instance=instance,
            key=instance.id if instance is not None else "",
        )
        self._bus.emit(events.EventType.INSTANCE_CHANGED, payload)


_manager: InstanceManager | None = None
_manager_lock = threading.RLock()


def get_instance_manager() -> InstanceManager:
    """返回进程级实例管理器单例。"""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = InstanceManager()
        return _manager


def set_instance_manager(manager: InstanceManager | None) -> None:
    global _manager
    with _manager_lock:
        _manager = manager
