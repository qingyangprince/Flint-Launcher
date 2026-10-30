"""Minecraft 版本元数据：manifest 拉取、继承链合并与 rules 过滤。"""

from __future__ import annotations

import copy
import json
import logging
import platform as _platform
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flint.infra import cache as http_cache
from flint.infra import http
from flint.platform import paths

logger = logging.getLogger(__name__)

OFFICIAL_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
BMCLAPI_MANIFEST_URL = "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"

MANIFEST_URLS = {
    "official": OFFICIAL_MANIFEST_URL,
    "bmclapi": BMCLAPI_MANIFEST_URL,
}

DEFAULT_MANIFEST_MAX_AGE = 600.0
MAX_INHERITANCE_DEPTH = 10
_MERGE_EXCLUDED = {"libraries", "arguments"}


class VersionError(Exception):
    """版本元数据缺失、损坏或不一致时抛出。"""


class VersionNotFound(VersionError):
    """请求的版本 id 不存在时抛出。"""


@dataclass(frozen=True)
class VersionSummary:
    id: str
    type: str
    url: str
    time: str = ""
    release_time: str = ""
    sha1: str | None = None
    compliance_level: int | None = None


@dataclass(frozen=True)
class VersionManifest:
    latest_release: str
    latest_snapshot: str
    versions: tuple[VersionSummary, ...]

    @classmethod
    def from_json(cls, data: Any) -> VersionManifest:
        if not isinstance(data, Mapping):
            raise VersionError("malformed version manifest: expected an object")
        raw_versions = data.get("versions")
        if not isinstance(raw_versions, list) or not raw_versions:
            raise VersionError("malformed version manifest: missing 'versions' list")

        versions: list[VersionSummary] = []
        for entry in raw_versions:
            if not isinstance(entry, Mapping):
                logger.warning("skipping malformed version entry: %r", entry)
                continue
            version_id, url = entry.get("id"), entry.get("url")
            if not isinstance(version_id, str) or not isinstance(url, str):
                logger.warning("skipping version entry without id/url: %r", entry)
                continue
            versions.append(
                VersionSummary(
                    id=version_id,
                    type=str(entry.get("type", "")),
                    url=url,
                    time=str(entry.get("time", "")),
                    release_time=str(entry.get("releaseTime", "")),
                    sha1=entry.get("sha1"),
                    compliance_level=entry.get("complianceLevel"),
                )
            )

        if not versions:
            raise VersionError("malformed version manifest: no usable version entries")

        latest = data.get("latest") if isinstance(data.get("latest"), Mapping) else {}
        latest_release = (
            latest.get("release") or _latest_of_type(versions, "release") or versions[0].id
        )
        latest_snapshot = (
            latest.get("snapshot") or _latest_of_type(versions, "snapshot") or versions[0].id
        )
        return cls(
            latest_release=str(latest_release),
            latest_snapshot=str(latest_snapshot),
            versions=tuple(versions),
        )

    def find(self, version_id: str) -> VersionSummary | None:
        for version in self.versions:
            if version.id == version_id:
                return version
        return None

    def latest_of(self, channel: str = "release") -> VersionSummary | None:
        target = self.latest_release if channel == "release" else self.latest_snapshot
        return self.find(target) or next((v for v in self.versions if v.type == channel), None)

    def filter(self, channel: str | None = None) -> list[VersionSummary]:
        if channel is None:
            return list(self.versions)
        return [version for version in self.versions if version.type == channel]

    def __len__(self) -> int:
        return len(self.versions)


@dataclass(frozen=True)
class ResolvedVersion:
    """已完全合并、并已按宿主系统过滤的版本文档。"""

    id: str
    type: str = ""
    main_class: str = ""
    assets: str = "legacy"
    asset_index: dict[str, Any] | None = None
    downloads: dict[str, Any] = field(default_factory=dict)
    libraries: tuple[dict[str, Any], ...] = ()
    arguments: dict[str, Any] = field(default_factory=dict)
    minecraft_arguments: str | None = None
    java_version: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    jar: str | None = None
    minimum_launcher_version: int | None = None
    release_time: str | None = None
    time: str | None = None
    inherited_from: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def client_download(self) -> dict[str, Any] | None:
        client = self.downloads.get("client") if isinstance(self.downloads, Mapping) else None
        return client if isinstance(client, dict) else None

    @property
    def client_jar_name(self) -> str:
        return f"{self.id}.jar"

    @property
    def recommended_java_major(self) -> int | None:
        if isinstance(self.java_version, Mapping):
            major = self.java_version.get("majorVersion")
            return int(major) if isinstance(major, int) else None
        return None


def current_os() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "osx"
    return "linux"


def current_arch() -> str:
    machine = _platform.machine().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    if machine in {"i386", "i486", "i586", "i686", "x86"}:
        return "x86"
    return machine


def rule_matches(
    rule: Mapping[str, Any],
    *,
    os_name: str,
    arch: str,
    features: Mapping[str, bool],
) -> bool:
    os_rule = rule.get("os")
    if isinstance(os_rule, Mapping):
        name = os_rule.get("name")
        if name and name != os_name:
            return False
        rule_arch = os_rule.get("arch")
        if rule_arch:
            if rule_arch == "x86":
                if arch != "x86":
                    return False
            elif rule_arch != arch:
                return False
        version_pattern = os_rule.get("version")
        if isinstance(version_pattern, str) and version_pattern:
            try:
                if not re.search(version_pattern, _platform.release()):
                    return False
            except re.error:
                logger.warning("invalid os.version regex in rule: %r", version_pattern)
                return False

    features_rule = rule.get("features")
    if isinstance(features_rule, Mapping):
        for key, expected in features_rule.items():
            if bool(features.get(str(key), False)) != bool(expected):
                return False
    return True


def rules_allow(
    rules: Sequence[Mapping[str, Any]] | None,
    *,
    os_name: str | None = None,
    arch: str | None = None,
    features: Mapping[str, bool] | None = None,
) -> bool:
    """求值 Mojang ``rules``；列表为空或缺失时一律允许。"""
    if not rules:
        return True
    os_name = os_name or current_os()
    arch = arch or current_arch()
    features = features or {}

    allowed = False
    for rule in rules:
        if not isinstance(rule, Mapping):
            continue
        if rule_matches(rule, os_name=os_name, arch=arch, features=features):
            allowed = rule.get("action", "allow") == "allow"
    return allowed


def filter_libraries(
    libraries: Iterable[Mapping[str, Any]],
    *,
    os_name: str | None = None,
    arch: str | None = None,
    features: Mapping[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """返回当前 OS/架构下允许使用的 libraries 深拷贝列表。"""
    result: list[dict[str, Any]] = []
    for library in libraries:
        if not isinstance(library, Mapping):
            continue
        if not rules_allow(library.get("rules"), os_name=os_name, arch=arch, features=features):
            continue
        result.append(copy.deepcopy(dict(library)))
    return result


def library_key(library: Mapping[str, Any]) -> str | None:
    """以 ``group:artifact`` 作为 libraries 的分组键，供继承链去重。"""
    name = library.get("name")
    if not isinstance(name, str):
        return None
    parts = name.split(":")
    if len(parts) < 2:
        return name or None
    return ":".join(parts[:2])


def merge_version_json(child: Mapping[str, Any], parent: Mapping[str, Any]) -> dict[str, Any]:
    """按 Mojang 继承规则把 ``child`` 覆盖合并到 ``parent`` 之上。"""
    if not isinstance(child, Mapping) or not isinstance(parent, Mapping):
        raise VersionError("version merge requires two mapping objects")

    merged: dict[str, Any] = copy.deepcopy(dict(parent))
    for key, value in child.items():
        if key in _MERGE_EXCLUDED:
            continue
        merged[key] = copy.deepcopy(value)

    merged["libraries"] = _merge_libraries(parent.get("libraries"), child.get("libraries"))
    merged_arguments = _merge_arguments(parent.get("arguments"), child.get("arguments"))
    if merged_arguments is None:
        merged.pop("arguments", None)
    else:
        merged["arguments"] = merged_arguments

    merged["id"] = child.get("id") or parent.get("id") or ""
    return merged


def _merge_libraries(parent: Any, child: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    positions: dict[str, int] = {}

    for library in _as_list(parent) + _as_list(child):
        if not isinstance(library, Mapping):
            continue
        entry = copy.deepcopy(dict(library))
        key = library_key(library)
        if key is None:
            result.append(entry)
            continue
        index = positions.get(key)
        if index is None:
            positions[key] = len(result)
            result.append(entry)
        else:
            result[index] = entry
    return result


def _merge_arguments(parent: Any, child: Any) -> dict[str, Any] | None:
    parent_args = parent if isinstance(parent, Mapping) else {}
    child_args = child if isinstance(child, Mapping) else {}
    if not parent_args and not child_args:
        return None

    result: dict[str, Any] = {}
    ordered_keys = list(dict.fromkeys(list(parent_args.keys()) + list(child_args.keys())))
    for key in ordered_keys:
        if key in {"game", "jvm"}:
            combined = _as_list(parent_args.get(key)) + _as_list(child_args.get(key))
            if combined:
                result[key] = combined
        else:
            source = child_args if key in child_args else parent_args
            result[key] = copy.deepcopy(source[key])
    return result


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _resolve_chain(chain: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not chain:
        raise VersionError("empty inheritance chain")
    merged = copy.deepcopy(dict(chain[-1]))
    for node in reversed(chain[:-1]):
        merged = merge_version_json(node, merged)
    merged.pop("inheritsFrom", None)
    return merged


def build_resolved(
    merged: Mapping[str, Any],
    *,
    inherited_from: Sequence[str] = (),
    os_name: str | None = None,
    arch: str | None = None,
    features: Mapping[str, bool] | None = None,
) -> ResolvedVersion:
    """把合并后的版本文档转换为 :class:`ResolvedVersion`。"""
    main_class = merged.get("mainClass")
    if not isinstance(main_class, str) or not main_class:
        raise VersionError(f"version {merged.get('id')!r} has no mainClass")

    libraries = filter_libraries(
        merged.get("libraries") or [], os_name=os_name, arch=arch, features=features
    )
    arguments = merged.get("arguments")
    asset_index = merged.get("assetIndex")
    downloads = merged.get("downloads")
    java_version = merged.get("javaVersion")
    logging_config = merged.get("logging")
    minimum_launcher = merged.get("minimumLauncherVersion")

    return ResolvedVersion(
        id=str(merged.get("id", "")),
        type=str(merged.get("type", "")),
        main_class=main_class,
        assets=str(merged.get("assets", "legacy")),
        asset_index=copy.deepcopy(asset_index) if isinstance(asset_index, Mapping) else None,
        downloads=copy.deepcopy(dict(downloads)) if isinstance(downloads, Mapping) else {},
        libraries=tuple(libraries),
        arguments=copy.deepcopy(dict(arguments)) if isinstance(arguments, Mapping) else {},
        minecraft_arguments=merged.get("minecraftArguments"),
        java_version=copy.deepcopy(dict(java_version))
        if isinstance(java_version, Mapping)
        else None,
        logging=copy.deepcopy(dict(logging_config))
        if isinstance(logging_config, Mapping)
        else None,
        jar=merged.get("jar"),
        minimum_launcher_version=int(minimum_launcher)
        if isinstance(minimum_launcher, int)
        else None,
        release_time=merged.get("releaseTime"),
        time=merged.get("time"),
        inherited_from=tuple(inherited_from),
        raw=copy.deepcopy(dict(merged)),
    )


def resolve_json(
    raw: Mapping[str, Any],
    parent_loader: Callable[[str], Mapping[str, Any]],
    *,
    os_name: str | None = None,
    arch: str | None = None,
    features: Mapping[str, bool] | None = None,
) -> ResolvedVersion:
    """同步解析版本文档及其 ``inheritsFrom`` 继承链。"""
    if not isinstance(raw, Mapping):
        raise VersionError("version document must be an object")

    chain: list[Mapping[str, Any]] = [raw]
    seen = {str(raw.get("id", ""))}
    current = raw
    while True:
        parent_id = current.get("inheritsFrom")
        if not parent_id:
            break
        if not isinstance(parent_id, str):
            raise VersionError(f"invalid inheritsFrom value: {parent_id!r}")
        if parent_id in seen:
            raise VersionError(f"cyclic version inheritance detected at {parent_id!r}")
        if len(chain) >= MAX_INHERITANCE_DEPTH:
            raise VersionError(f"version inheritance chain too deep at {parent_id!r}")
        seen.add(parent_id)
        try:
            parent = parent_loader(parent_id)
        except VersionNotFound as exc:
            raise VersionNotFound(
                f"version {raw.get('id')!r} inherits from missing version {parent_id!r}"
            ) from exc
        if not isinstance(parent, Mapping):
            raise VersionError(f"parent version {parent_id!r} is not a JSON object")
        chain.append(parent)
        current = parent

    merged = _resolve_chain(chain)
    inherited = tuple(str(node.get("id", "")) for node in chain[1:])
    return build_resolved(
        merged, inherited_from=inherited, os_name=os_name, arch=arch, features=features
    )


def _latest_of_type(versions: Iterable[VersionSummary], channel: str) -> str | None:
    for version in versions:
        if version.type == channel:
            return version.id
    return None


class VersionResolver:
    """拉取 manifest/版本 JSON（带 ETag 缓存）并解析继承链。"""

    def __init__(
        self,
        client: http.HttpClient | None = None,
        cache: http_cache.HttpCache | None = None,
        *,
        version_dir: Path | str | None = None,
        mirror: str = "official",
        manifest_url: str | None = None,
        os_name: str | None = None,
        arch: str | None = None,
        features: Mapping[str, bool] | None = None,
    ) -> None:
        self._client = client
        self._cache = cache if cache is not None else http_cache.HttpCache(paths.http_cache_dir())
        self.version_dir = Path(version_dir) if version_dir is not None else paths.versions_dir()
        self.mirror = mirror
        self.manifest_url = manifest_url or MANIFEST_URLS.get(mirror, OFFICIAL_MANIFEST_URL)
        self.os_name = os_name or current_os()
        self.arch = arch or current_arch()
        self.features = dict(features or {})
        self._manifest: VersionManifest | None = None

    @property
    def client(self) -> http.HttpClient:
        if self._client is None:
            self._client = http.get_client()
        return self._client

    async def fetch_manifest(self, *, force: bool = False) -> VersionManifest:
        if self._manifest is not None and not force:
            return self._manifest
        try:
            data = await self._cache.fetch_json(
                self.client, self.manifest_url, max_age=DEFAULT_MANIFEST_MAX_AGE, force=force
            )
        except http.HttpError as exc:
            raise VersionError(f"cannot fetch version manifest {self.manifest_url}: {exc}") from exc
        self._manifest = VersionManifest.from_json(data)
        return self._manifest

    async def fetch_version_json(self, url: str, *, force: bool = False) -> dict[str, Any]:
        try:
            data = await self._cache.fetch_json(self.client, url, force=force)
        except http.HttpError as exc:
            raise VersionError(f"cannot fetch version json {url}: {exc}") from exc
        if not isinstance(data, dict):
            raise VersionError(f"version json at {url} is not an object")
        return data

    async def resolve(
        self,
        version_id: str,
        *,
        url: str | None = None,
        force: bool = False,
    ) -> ResolvedVersion:
        raw = await self._load_version(version_id, url=url, force=force)
        chain: list[dict[str, Any]] = [raw]
        seen = {version_id}
        current = raw

        while True:
            parent_id = current.get("inheritsFrom")
            if not parent_id:
                break
            if not isinstance(parent_id, str):
                raise VersionError(f"invalid inheritsFrom value: {parent_id!r}")
            if parent_id in seen:
                raise VersionError(f"cyclic version inheritance detected at {parent_id!r}")
            if len(chain) >= MAX_INHERITANCE_DEPTH:
                raise VersionError(f"version inheritance chain too deep at {parent_id!r}")
            seen.add(parent_id)
            parent = await self._load_version(parent_id, force=force)
            chain.append(parent)
            current = parent

        merged = _resolve_chain(chain)
        inherited = tuple(str(node.get("id", "")) for node in chain[1:])
        return build_resolved(
            merged,
            inherited_from=inherited,
            os_name=self.os_name,
            arch=self.arch,
            features=self.features,
        )

    def resolve_local(self, version_id: str) -> ResolvedVersion:
        """只使用本地 ``versions/`` 目录进行解析。"""
        raw = self.read_local_json(version_id)
        if raw is None:
            raise VersionNotFound(f"version {version_id!r} is not installed")

        def parent_loader(parent_id: str) -> Mapping[str, Any]:
            parent = self.read_local_json(parent_id)
            if parent is None:
                raise VersionNotFound(parent_id)
            return parent

        return resolve_json(
            raw,
            parent_loader,
            os_name=self.os_name,
            arch=self.arch,
            features=self.features,
        )

    def read_local_json(self, version_id: str) -> dict[str, Any] | None:
        """读取 ``versions/<id>/<id>.json``（或旧的扁平布局）。"""
        candidates = [
            self.version_dir / version_id / f"{version_id}.json",
            self.version_dir / f"{version_id}.json",
            self.version_dir / version_id / "version.json",
        ]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise VersionError(f"corrupt version json {candidate}: {exc}") from exc
            if not isinstance(data, dict):
                raise VersionError(f"version json {candidate} is not an object")
            return data
        return None

    async def _load_version(
        self, version_id: str, *, url: str | None = None, force: bool = False
    ) -> dict[str, Any]:
        local = self.read_local_json(version_id)
        if local is not None:
            return local
        if url is None:
            manifest = await self.fetch_manifest(force=force)
            summary = manifest.find(version_id)
            if summary is None:
                raise VersionNotFound(f"unknown Minecraft version: {version_id!r}")
            url = summary.url
        return await self.fetch_version_json(url, force=force)
