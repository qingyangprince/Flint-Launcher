"""启动命令构造、libraries/assets 计划与启动前置校验。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from flint.core import assets as assets_module
from flint.core import libraries
from flint.core.account import Account, AccountType
from flint.core.instance import Instance
from flint.core.launcher import (
    JavaNotFoundError,
    Launcher,
    LaunchError,
    LaunchOptions,
    MissingAccountError,
    build_command,
)
from flint.core.version import ResolvedVersion
from flint.platform import java as java_module


def _account(name: str = "Steve") -> Account:
    return Account(name=name, type=AccountType.OFFLINE)


def _version(**overrides) -> ResolvedVersion:
    data = {
        "id": "1.20.1",
        "type": "release",
        "main_class": "net.minecraft.client.main.Main",
        "assets": "5",
        "arguments": {
            "jvm": [
                "-Djava.library.path=${natives_directory}",
                "-cp",
                "${classpath}",
                {
                    "rules": [{"action": "allow", "os": {"name": "osx"}}],
                    "value": ["-XstartOnFirstThread"],
                },
            ],
            "game": [
                "--username",
                "${auth_player_name}",
                "--uuid",
                "${auth_uuid}",
                "--accessToken",
                "${auth_access_token}",
                "--version",
                "${version_name}",
                "--gameDir",
                "${game_directory}",
                "--assetsDir",
                "${assets_root}",
                "--assetIndex",
                "${assets_index_name}",
                "--userType",
                "${user_type}",
            ],
        },
    }
    data.update(overrides)
    return ResolvedVersion(**data)


def test_build_command_substitutes_context(tmp_path: Path) -> None:
    account = _account()
    options = LaunchOptions(game_dir=tmp_path / "game", memory_mb=4096, width=1280, height=720)
    classpath = [tmp_path / "a.jar", tmp_path / "b.jar"]

    command = build_command(
        _version(),
        java="/usr/bin/java",
        options=options,
        account=account,
        classpath=classpath,
        natives_dir=tmp_path / "natives",
        assets_dir=tmp_path / "assets",
        asset_index="5",
    )

    assert command[0] == "/usr/bin/java"
    assert "-Xmx4096m" in command
    assert "-Djava.library.path=" + str(tmp_path / "natives") in command
    assert command[command.index("-cp") + 1] == os.pathsep.join(str(p) for p in classpath)
    main_index = command.index("net.minecraft.client.main.Main")
    assert command[main_index + 1] == "--username"
    assert "Steve" in command
    assert account.uuid in command
    assert "legacy" in command
    assert "-XstartOnFirstThread" not in command  # macOS-only 规则

    assert str(tmp_path / "game") in command
    assert str(tmp_path / "assets") in command
    assert "5" in command


def test_build_command_legacy_minecraft_arguments(tmp_path: Path) -> None:
    version = _version(
        arguments={},
        minecraft_arguments="--username ${auth_player_name} --gameDir ${game_directory}",
    )
    options = LaunchOptions(game_dir=tmp_path)
    command = build_command(
        version,
        java="java",
        options=options,
        account=_account("Alex"),
        classpath=[tmp_path / "client.jar"],
        natives_dir=tmp_path / "natives",
        assets_dir=tmp_path,
        asset_index="legacy",
    )

    assert command[command.index("net.minecraft.client.main.Main") + 1] == "--username"
    assert "Alex" in command


def test_build_command_adds_logging_and_user_jvm_args(tmp_path: Path) -> None:
    options = LaunchOptions(game_dir=tmp_path, jvm_args=("-XX:+UseG1GC",))
    command = build_command(
        _version(),
        java="java",
        options=options,
        account=_account(),
        classpath=[],
        natives_dir=tmp_path,
        assets_dir=tmp_path,
        asset_index="5",
        logging_config=tmp_path / "log4j.xml",
    )
    assert "-XX:+UseG1GC" in command
    assert f"-Dlog4j.configurationFile={tmp_path / 'log4j.xml'}" in command


def test_library_plan_separates_natives(tmp_path: Path) -> None:
    version = ResolvedVersion(
        id="1.12.2",
        main_class="Main",
        libraries=(
            {
                "name": "org.lwjgl:lwjgl:3.1.6",
                "downloads": {
                    "artifact": {
                        "path": "org/lwjgl/lwjgl/3.1.6/lwjgl-3.1.6.jar",
                        "url": f"{libraries.LIBRARIES_BASE}org/lwjgl/lwjgl/3.1.6/lwjgl-3.1.6.jar",
                        "sha1": "abc",
                        "size": 100,
                    },
                    "classifiers": {
                        "natives-windows": {
                            "path": "org/lwjgl/lwjgl/3.1.6/lwjgl-3.1.6-natives-windows.jar",
                            "url": f"{libraries.LIBRARIES_BASE}org/lwjgl/lwjgl/3.1.6/lwjgl-3.1.6-natives-windows.jar",
                        }
                    },
                },
                "natives": {"windows": "natives-windows"},
                "extract": {"exclude": ["META-INF/"]},
            },
            {
                "name": "com.example:modern-natives:1.0:natives-windows",
                "downloads": {
                    "artifact": {"path": "com/example/modern-natives/1.0/modern-natives-1.0-natives-windows.jar"}
                },
            },
        ),
    )

    files = libraries.build_library_files(version, root=tmp_path, os_name="windows")

    native_names = {item.name for item in libraries.native_files(files)}
    classpath_names = [item.path.name for item in files if not item.native]
    assert "org.lwjgl:lwjgl:3.1.6" in native_names
    assert "com.example:modern-natives:1.0:natives-windows" in native_names
    assert "lwjgl-3.1.6.jar" in classpath_names
    assert "lwjgl-3.1.6-natives-windows.jar" not in classpath_names
    assert all(item.extract == ("META-INF/",) for item in libraries.native_files(files))


def test_asset_plan_paths_and_missing(tmp_path: Path) -> None:
    index = assets_module.parse_index(
        {"objects": {"minecraft/sounds/click.ogg": {"hash": "abcdef1234", "size": 4}}}
    )
    files = assets_module.build_asset_files(index, root=tmp_path)

    assert len(files) == 1
    item = files[0]
    assert item.path == tmp_path / "objects" / "ab" / "abcdef1234"
    assert item.url.endswith("/ab/abcdef1234")
    assert assets_module.missing_assets(files) == files

    item.path.parent.mkdir(parents=True)
    item.path.write_bytes(b"data")
    assert assets_module.missing_assets(files) == []


def test_launcher_prepare_without_files_reports_missing(flint_home: Path, monkeypatch) -> None:
    version_dir = flint_home / "versions" / "1.20.1"
    version_dir.mkdir(parents=True)
    (version_dir / "1.20.1.json").write_text(
        json.dumps(
            {
                "id": "1.20.1",
                "mainClass": "net.minecraft.client.main.Main",
                "assets": "5",
                "assetIndex": {"id": "5", "url": "https://example.com/5.json"},
                "downloads": {
                    "client": {
                        "url": "https://example.com/client.jar",
                        "sha1": "0" * 40,
                        "size": 1,
                    }
                },
                "libraries": [],
            }
        ),
        encoding="utf-8",
    )
    runtime = java_module.JavaRuntime(
        path=Path("java"), version="17.0.8", major=17, vendor="Temurin"
    )
    monkeypatch.setattr(java_module, "find_java", lambda *args, **kwargs: runtime)

    manager_instance = Instance(name="Smoke", version="1.20.1")
    launcher = Launcher(instances_root=flint_home / "instances")

    plan = _run(launcher.prepare(manager_instance, _account(), download=False))

    assert plan.command[0] == str(Path("java"))
    assert plan.missing, "expected missing files for a fresh install"
    assert any("客户端 jar" in item for item in plan.missing)


def test_launcher_requires_account(flint_home: Path, monkeypatch) -> None:
    runtime = java_module.JavaRuntime(path=Path("java"), version="17", major=17)
    monkeypatch.setattr(java_module, "find_java", lambda *args, **kwargs: runtime)
    launcher = Launcher(instances_root=flint_home / "instances")

    with pytest.raises(MissingAccountError):
        _run(launcher.prepare(Instance(name="X", version="1.20.1"), None, download=False))


def test_launcher_reports_missing_java(flint_home: Path, monkeypatch) -> None:
    version_dir = flint_home / "versions" / "1.20.1"
    version_dir.mkdir(parents=True)
    (version_dir / "1.20.1.json").write_text(
        json.dumps({"id": "1.20.1", "mainClass": "Main", "assets": "5"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(java_module, "find_java", lambda *args, **kwargs: None)
    launcher = Launcher(instances_root=flint_home / "instances")

    with pytest.raises(JavaNotFoundError):
        _run(launcher.prepare(Instance(name="X", version="1.20.1"), _account(), download=False))


def test_launcher_wraps_resolution_errors(flint_home: Path, monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("offline")

    launcher = Launcher(instances_root=flint_home / "instances")
    monkeypatch.setattr(launcher.resolver, "resolve", boom)

    with pytest.raises(LaunchError):
        _run(launcher.prepare(Instance(name="X", version="missing"), _account(), download=False))


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)
