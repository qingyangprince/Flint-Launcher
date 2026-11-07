"""启动编排：解析版本、补齐文件、拼装 JVM/游戏参数并拉起 Java 进程。"""

from __future__ import annotations

import logging
import os
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flint import __version__
from flint.core import assets as assets_module
from flint.core import config as config_module
from flint.core import events, libraries
from flint.core.account import Account
from flint.core.instance import Instance
from flint.core.version import ResolvedVersion, VersionResolver, rules_allow
from flint.infra import downloader as downloader_module
from flint.infra import extract, fs, http
from flint.infra import process as process_module
from flint.platform import java as java_module
from flint.platform import paths

logger = logging.getLogger(__name__)

BMCLAPI_VERSION_BASE = "https://bmclapi2.bangbang93.com/version/"

ProgressCallback = Callable[[float, str], None]
LineCallback = Callable[[str], None]


class LaunchError(Exception):
    """启动前置条件不满足或进程拉起失败。"""


class JavaNotFoundError(LaunchError):
    """找不到可用的 Java。"""


class MissingAccountError(LaunchError):
    """启动需要账户但当前没有选中账户。"""


class MissingFilesError(LaunchError):
    """启动所需文件缺失（自动下载关闭或下载失败）。"""

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = tuple(missing)
        preview = "、".join(self.missing[:5])
        suffix = f" 等 {len(self.missing)} 项" if len(self.missing) > 5 else ""
        super().__init__(f"启动所需文件缺失：{preview}{suffix}")


@dataclass(frozen=True)
class LaunchOptions:
    """与实例/账户无关的启动偏好。"""

    game_dir: Path
    memory_mb: int = 2048
    width: int | None = None
    height: int | None = None
    fullscreen: bool = False
    demo: bool = False
    jvm_args: tuple[str, ...] = ()
    game_args: tuple[str, ...] = ()
    launcher_name: str = "flint"
    launcher_version: str = __version__


@dataclass(frozen=True)
class LaunchPlan:
    """一次启动的完整命令与统计信息。"""

    command: tuple[str, ...]
    cwd: Path
    main_class: str
    classpath: tuple[Path, ...]
    natives_dir: Path
    java: java_module.JavaRuntime | None = None
    missing: tuple[str, ...] = ()

    @property
    def display_command(self) -> str:
        return " ".join(shlex.quote(part) for part in self.command)


def _substitute(value: str, context: Mapping[str, str]) -> str:
    result = value
    for key, replacement in context.items():
        result = result.replace("${" + key + "}", replacement)
    return result


def _split_args(raw: str) -> tuple[str, ...]:
    """拆分用户填写的附加参数；Windows 下保留反斜杠。"""
    if not raw.strip():
        return ()
    try:
        parts = shlex.split(raw, posix=os.name != "nt")
    except ValueError:
        parts = raw.split()
    return tuple(part for part in parts if part)


def _features(options: LaunchOptions) -> dict[str, bool]:
    return {
        "is_demo_user": options.demo,
        "has_custom_resolution": bool(options.width and options.height),
        "has_quick_plays_support": False,
        "is_quick_play_singleplayer": False,
        "is_quick_play_multiplayer": False,
        "is_quick_play_realms": False,
    }


def _mentions(entries: Sequence[Any], needle: str) -> bool:
    for entry in entries:
        if isinstance(entry, str) and needle in entry:
            return True
        if isinstance(entry, Mapping):
            value = entry.get("value")
            if isinstance(value, str) and needle in value:
                return True
            if isinstance(value, Sequence) and any(
                isinstance(item, str) and needle in item for item in value
            ):
                return True
    return False


def _collect_arguments(
    entries: Sequence[Any] | None,
    context: Mapping[str, str],
    features: Mapping[str, bool],
) -> list[str]:
    """展开 ``arguments.game`` / ``arguments.jvm``（字符串或带 rules 的对象）。"""
    result: list[str] = []
    for entry in entries or ():
        if isinstance(entry, str):
            result.append(_substitute(entry, context))
            continue
        if not isinstance(entry, Mapping):
            continue
        if not rules_allow(entry.get("rules"), features=features):
            continue
        value = entry.get("value")
        if isinstance(value, str):
            result.append(_substitute(value, context))
        elif isinstance(value, Sequence):
            for item in value:
                if isinstance(item, str):
                    result.append(_substitute(item, context))
    return result


def build_command(
    version: ResolvedVersion,
    *,
    java: Path | str,
    options: LaunchOptions,
    account: Account,
    classpath: Sequence[Path],
    natives_dir: Path,
    assets_dir: Path,
    asset_index: str,
    logging_config: Path | None = None,
) -> list[str]:
    """构造完整命令行；纯函数，便于测试。"""
    features = _features(options)
    context = {
        "auth_player_name": account.name,
        "version_name": version.id,
        "game_directory": str(options.game_dir),
        "assets_root": str(assets_dir),
        "game_assets": str(assets_dir),
        "assets_index_name": asset_index,
        "auth_uuid": account.uuid,
        "auth_access_token": account.access_token or "0",
        "auth_session": account.access_token or "0",
        "clientid": "",
        "auth_xuid": "",
        "user_type": "msa" if account.is_microsoft else "legacy",
        "version_type": version.type or "release",
        "user_properties": "{}",
        "natives_directory": str(natives_dir),
        "launcher_name": options.launcher_name,
        "launcher_version": options.launcher_version,
        "classpath": os.pathsep.join(str(item) for item in classpath),
        "classpath_separator": os.pathsep,
        "library_directory": str(paths.libraries_dir()),
        "resolution_width": str(options.width or 854),
        "resolution_height": str(options.height or 480),
    }

    command: list[str] = [str(java), f"-Xmx{options.memory_mb}m"]
    if logging_config is not None:
        command.append(f"-Dlog4j.configurationFile={logging_config}")
    command.extend(
        [
            f"-Dminecraft.launcher.brand={options.launcher_name}",
            f"-Dminecraft.launcher.version={options.launcher_version}",
        ]
    )
    command.extend(options.jvm_args)

    jvm_entries = version.arguments.get("jvm") if version.arguments else None
    if isinstance(jvm_entries, Sequence) and jvm_entries:
        command.extend(_collect_arguments(jvm_entries, context, features))
        if not _mentions(jvm_entries, "${classpath}"):
            command.extend(["-cp", context["classpath"]])
    else:
        command.extend(
            [
                f"-Djava.library.path={natives_dir}",
                "-cp",
                context["classpath"],
            ]
        )

    command.append(version.main_class)

    game_entries = version.arguments.get("game") if version.arguments else None
    if isinstance(game_entries, Sequence) and game_entries:
        command.extend(_collect_arguments(game_entries, context, features))
    elif version.minecraft_arguments:
        command.extend(
            _substitute(part, context) for part in shlex.split(version.minecraft_arguments)
        )
    command.extend(options.game_args)
    return command


class Launcher:
    """把实例 + 账户 + Java 变成一条可执行的命令。"""

    def __init__(
        self,
        *,
        config: config_module.Config | None = None,
        resolver: VersionResolver | None = None,
        downloader: downloader_module.Downloader | None = None,
        client: http.HttpClient | None = None,
        instances_root: Path | str | None = None,
    ) -> None:
        self._config = config
        self._resolver = resolver
        self._downloader = downloader
        self._client = client
        self.instances_root = (
            Path(instances_root) if instances_root is not None else paths.instances_dir()
        )

    @property
    def config(self) -> config_module.Config:
        if self._config is None:
            self._config = config_module.get_config()
        return self._config

    @property
    def resolver(self) -> VersionResolver:
        if self._resolver is None:
            self._resolver = VersionResolver(mirror=str(self.config.get("download.mirror")))
        return self._resolver

    @property
    def downloader(self) -> downloader_module.Downloader:
        if self._downloader is None:
            self._downloader = downloader_module.Downloader(
                self._client,
                max_concurrency=int(self.config.get("download.max_concurrency")),
                retries=int(self.config.get("download.retries")),
            )
        return self._downloader

    async def prepare(
        self,
        instance: Instance,
        account: Account | None = None,
        *,
        download: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> LaunchPlan:
        """解析版本并（可选）补齐文件，返回可执行计划。"""
        if account is None:
            raise MissingAccountError("启动前请先选择或添加账户")

        resolved = await self._resolve(instance)
        java_runtime = self._find_java(instance, resolved)
        if java_runtime is None:
            recommended = java_module.recommend_major(instance.version, resolved.java_version)
            raise JavaNotFoundError(
                f"未找到 Java {recommended}（Minecraft {instance.version} 需要）；"
                "请在设置中手动指定 java 路径"
            )

        mirror = str(self.config.get("download.mirror"))
        library_files = libraries.build_library_files(resolved, mirror=mirror)
        client_jar = self._client_jar_path(resolved)
        index_file = assets_module.index_path(resolved.assets)

        if download and not index_file.is_file() and resolved.asset_index:
            await self._download_tasks([self._asset_index_task(resolved, index_file)], on_progress)

        asset_objects = self._read_asset_index(index_file)
        asset_files = assets_module.build_asset_files(asset_objects, mirror=mirror)

        if download:
            await self._download_tasks(
                self._library_tasks(library_files, mirror)
                + self._asset_tasks(asset_files)
                + self._client_task(resolved, client_jar)
                + self._logging_task(resolved),
                on_progress,
            )

        missing = self._missing_names(
            resolved, library_files, asset_files, client_jar, index_file
        )
        if missing and download:
            raise MissingFilesError(missing)

        natives_dir = paths.natives_dir() / instance.id
        if download:
            self._extract_natives(library_files, natives_dir)
            native_missing = [
                item for item in libraries.native_files(library_files) if not item.path.is_file()
            ]
            if native_missing:
                raise MissingFilesError([item.name for item in native_missing])

        options = self._options(instance)
        cp = [*libraries.classpath(library_files), client_jar]
        command = build_command(
            resolved,
            java=java_runtime.path,
            options=options,
            account=account,
            classpath=cp,
            natives_dir=natives_dir,
            assets_dir=assets_module.assets_root(),
            asset_index=resolved.assets,
            logging_config=self._logging_config_path(resolved),
        )
        return LaunchPlan(
            command=tuple(command),
            cwd=options.game_dir,
            main_class=resolved.main_class,
            classpath=tuple(cp),
            natives_dir=natives_dir,
            java=java_runtime,
            missing=tuple(missing),
        )

    async def launch(
        self,
        instance: Instance,
        account: Account | None = None,
        *,
        download: bool = True,
        on_progress: ProgressCallback | None = None,
        on_stdout: LineCallback | None = None,
        on_stderr: LineCallback | None = None,
    ) -> tuple[LaunchPlan, process_module.ManagedProcess]:
        """准备并启动游戏进程。"""
        plan = await self.prepare(instance, account, download=download, on_progress=on_progress)
        fs.ensure_dir(plan.cwd)
        events.log(f"启动 {instance.name}（{instance.version}）", source="launcher")
        process = await process_module.start_process(
            plan.command,
            cwd=plan.cwd,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )
        events.log(f"游戏进程已启动，PID {process.pid}", source="game")
        return plan, process

    # -- 内部实现 -----------------------------------------------------------
    async def _resolve(self, instance: Instance) -> ResolvedVersion:
        try:
            return await self.resolver.resolve(instance.version_id)
        except Exception as exc:
            raise LaunchError(f"无法解析版本 {instance.version_id}：{exc}") from exc

    def _find_java(
        self, instance: Instance, resolved: ResolvedVersion
    ) -> java_module.JavaRuntime | None:
        preferred = instance.java_path or str(self.config.get("launcher.java_path") or "")
        return java_module.find_java(
            instance.version,
            java_version=resolved.java_version,
            preferred=preferred or None,
        )

    def _options(self, instance: Instance) -> LaunchOptions:
        widths = int(self.config.get("launcher.game_width"))
        heights = int(self.config.get("launcher.game_height"))
        fullscreen = bool(self.config.get("launcher.fullscreen"))
        raw_jvm = str(self.config.get("launcher.jvm_args") or "")
        jvm_args = _split_args(raw_jvm)
        return LaunchOptions(
            game_dir=self.instances_root / instance.id,
            memory_mb=instance.memory_mb,
            width=None if fullscreen else widths,
            height=None if fullscreen else heights,
            fullscreen=fullscreen,
            jvm_args=jvm_args,
        )

    def _client_jar_path(self, version: ResolvedVersion) -> Path:
        jar_id = version.jar or version.id
        return self.resolver.version_dir / jar_id / f"{jar_id}.jar"

    def _logging_config_path(self, version: ResolvedVersion) -> Path | None:
        entry = _logging_file(version)
        if entry is None:
            return None
        file_id = entry.get("id")
        if not isinstance(file_id, str) or not file_id:
            return None
        return assets_module.assets_root() / "log_configs" / file_id

    def _read_asset_index(self, index_file: Path) -> dict[str, dict[str, Any]]:
        if not index_file.is_file():
            return {}
        import json

        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("cannot read asset index %s: %s", index_file, exc)
            return {}
        return assets_module.parse_index(data) if isinstance(data, Mapping) else {}

    def _missing_names(
        self,
        version: ResolvedVersion,
        library_files: Sequence[libraries.LibraryFile],
        asset_files: Sequence[assets_module.AssetFile],
        client_jar: Path,
        index_file: Path,
    ) -> list[str]:
        missing = [item.name for item in libraries.missing_files(library_files)]
        missing.extend(item.name for item in assets_module.missing_assets(list(asset_files)))
        if not client_jar.is_file():
            missing.append(f"{version.id} 客户端 jar")
        if version.asset_index and not index_file.is_file():
            missing.append(f"{version.assets} 资源索引")
        return missing

    def _library_tasks(
        self, files: Sequence[libraries.LibraryFile], mirror: str
    ) -> list[downloader_module.DownloadTask]:
        tasks = []
        for item in files:
            if not item.url:
                continue
            tasks.append(
                downloader_module.DownloadTask(
                    url=item.url,
                    dest=item.path,
                    sha1=item.sha1,
                    size=item.size,
                    mirrors=_mirror_candidates(item.url) if mirror != "bmclapi" else (),
                )
            )
        return tasks

    def _asset_tasks(
        self, files: Sequence[assets_module.AssetFile]
    ) -> list[downloader_module.DownloadTask]:
        return [
            downloader_module.DownloadTask(
                url=item.url,
                dest=item.path,
                sha1=item.sha1,
                size=item.size,
                mirrors=_mirror_candidates(item.url),
            )
            for item in files
        ]

    def _client_task(
        self, version: ResolvedVersion, destination: Path
    ) -> list[downloader_module.DownloadTask]:
        entry = version.client_download
        if not entry or not isinstance(entry.get("url"), str):
            return []
        jar_id = version.jar or version.id
        return [
            downloader_module.DownloadTask(
                url=str(entry["url"]),
                dest=destination,
                sha1=str(entry.get("sha1")) if entry.get("sha1") else None,
                size=int(entry["size"]) if entry.get("size") else None,
                mirrors=(f"{BMCLAPI_VERSION_BASE}{jar_id}/client",),
            )
        ]

    def _asset_index_task(
        self, version: ResolvedVersion, destination: Path
    ) -> downloader_module.DownloadTask:
        entry = version.asset_index or {}
        url = str(entry.get("url") or "")
        if not url:
            raise LaunchError(f"{version.id} 缺少 assetIndex.url")
        return downloader_module.DownloadTask(
            url=url,
            dest=destination,
            sha1=str(entry.get("sha1")) if entry.get("sha1") else None,
            size=int(entry["size"]) if entry.get("size") else None,
        )

    def _logging_task(
        self, version: ResolvedVersion
    ) -> list[downloader_module.DownloadTask]:
        entry = _logging_file(version)
        if entry is None:
            return []
        file_id = entry.get("id")
        url = entry.get("url")
        if not isinstance(file_id, str) or not isinstance(url, str) or not url:
            return []
        destination = assets_module.assets_root() / "log_configs" / file_id
        return [
            downloader_module.DownloadTask(
                url=url,
                dest=destination,
                sha1=str(entry.get("sha1")) if entry.get("sha1") else None,
                size=int(entry["size"]) if entry.get("size") else None,
            )
        ]

    async def _download_tasks(
        self,
        tasks: Sequence[downloader_module.DownloadTask],
        on_progress: ProgressCallback | None,
    ) -> None:
        if not tasks:
            return
        fractions: dict[str, float] = {}
        last_reported = -1.0

        def report(task: downloader_module.DownloadTask, done: int, total: int | None) -> None:
            nonlocal last_reported
            if on_progress is None:
                return
            fractions[str(task.dest)] = min(done / total, 1.0) if total else 0.0
            overall = sum(fractions.values()) / len(tasks)
            if overall - last_reported < 0.01 and overall < 1.0:
                return
            last_reported = overall
            on_progress(overall, f"下载 {task.dest.name}")

        try:
            await self.downloader.download_all(tasks, progress=report)
        except (downloader_module.DownloadError, OSError) as exc:
            raise LaunchError(f"下载启动文件失败：{exc}") from exc
        if on_progress is not None:
            on_progress(1.0, "下载完成")

    def _extract_natives(
        self, files: Sequence[libraries.LibraryFile], destination: Path
    ) -> None:
        natives = libraries.native_files(files)
        if not natives:
            return
        fs.ensure_dir(destination)
        for item in natives:
            if not item.path.is_file():
                continue
            try:
                members = extract.list_members(item.path)
            except (OSError, extract.ExtractionError) as exc:
                logger.warning("cannot read natives archive %s: %s", item.path, exc)
                continue
            for member in members:
                if member.endswith("/") or any(
                    member.startswith(prefix) for prefix in item.extract
                ):
                    continue
                try:
                    extract.extract_member(item.path, member, destination)
                except extract.ExtractionError:
                    logger.warning("skipping unsafe natives member %s from %s", member, item.path)


def _logging_file(version: ResolvedVersion) -> Mapping[str, Any] | None:
    logging_config = version.logging
    if not isinstance(logging_config, Mapping):
        return None
    client = logging_config.get("client")
    if not isinstance(client, Mapping):
        return None
    file_entry = client.get("file")
    return file_entry if isinstance(file_entry, Mapping) else None


def _mirror_candidates(url: str) -> tuple[str, ...]:
    if url.startswith(libraries.LIBRARIES_BASE):
        return (url.replace(libraries.LIBRARIES_BASE, libraries.BMCLAPI_MAVEN_BASE),)
    if url.startswith(assets_module.RESOURCES_BASE):
        return (url.replace(assets_module.RESOURCES_BASE, assets_module.BMCLAPI_RESOURCES_BASE),)
    return ()
