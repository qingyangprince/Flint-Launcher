"""实例 CRUD、复制、导入导出与事件。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from flint.core.events import EventType, InstanceChangedEvent
from flint.core.instance import (
    Instance,
    InstanceError,
    InstanceExists,
    InstanceManager,
    InstanceNotFound,
    normalize_loader,
    slugify,
)


def test_create_and_get(flint_home: Path) -> None:
    manager = InstanceManager()
    instance = manager.create(
        "我的世界", "1.20.1", loader="fabric", loader_version="0.15.7", memory_mb=4096
    )

    assert instance.id
    assert manager.meta_path(instance).is_file()
    assert manager.get(instance.id) == instance
    assert manager.get("我的世界") == instance
    assert manager.list() == [instance]


def test_create_rejects_duplicate_name(flint_home: Path) -> None:
    manager = InstanceManager()
    manager.create("Alice", "1.20.1")
    with pytest.raises(InstanceExists):
        manager.create("alice", "1.19.4")


@pytest.mark.parametrize("name", ["", "   ", "..", "a/b", "a:b", "x" * 65])
def test_invalid_names(flint_home: Path, name: str) -> None:
    manager = InstanceManager()
    with pytest.raises(InstanceError):
        manager.create(name, "1.20.1")


def test_unknown_loader_is_rejected(flint_home: Path) -> None:
    with pytest.raises(InstanceError):
        Instance(name="x", version="1.20.1", loader="optifine")
    assert normalize_loader("原版") == "vanilla"
    assert normalize_loader("NeoForge") == "neoforge"


def test_update_persists_and_validates(flint_home: Path) -> None:
    manager = InstanceManager()
    instance = manager.create("Base", "1.20.1")

    updated = manager.update(instance, name="Renamed", memory_mb=6144)
    assert updated.name == "Renamed"
    assert manager.get(instance.id).memory_mb == 6144
    assert manager.get("renamed").id == instance.id

    with pytest.raises(ValueError):
        manager.update(updated, memory_mb=1)


def test_clone_copies_game_files(flint_home: Path) -> None:
    manager = InstanceManager()
    instance = manager.create("Source", "1.20.1")
    mods = manager.directory_for(instance) / "mods"
    mods.mkdir()
    (mods / "example.jar").write_bytes(b"payload")

    cloned = manager.clone(instance, "Copy")
    assert cloned.id != instance.id
    assert (manager.directory_for(cloned) / "mods" / "example.jar").read_bytes() == b"payload"
    assert len(manager.list()) == 2


def test_delete_removes_directory(flint_home: Path) -> None:
    manager = InstanceManager()
    instance = manager.create("Temp", "1.20.1")
    directory = manager.directory_for(instance)

    manager.delete(instance)
    assert not directory.exists()
    with pytest.raises(InstanceNotFound):
        manager.get("temp")


def test_export_import_roundtrip(flint_home: Path, tmp_path: Path) -> None:
    manager = InstanceManager()
    instance = manager.create("Packaged", "1.19.4", loader="quilt", loader_version="0.2")
    saves = manager.directory_for(instance) / "saves" / "world"
    saves.mkdir(parents=True)
    (saves / "level.dat").write_bytes(b"level")

    archive = manager.export(instance, tmp_path / "packaged.zip")
    assert archive.is_file()

    other_root = tmp_path / "other-instances"
    other = InstanceManager(other_root)
    imported = other.import_instance(archive)
    assert imported.name == "Packaged"
    assert imported.loader == "quilt"
    assert (other.directory_for(imported) / "saves" / "world" / "level.dat").read_bytes() == b"level"


def test_import_rejects_archive_without_metadata(flint_home: Path, tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "broken.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("readme.txt", "nothing here")

    with pytest.raises(InstanceError):
        InstanceManager().import_instance(archive)


def test_events_are_emitted(flint_home: Path, event_bus) -> None:
    actions: list[str] = []

    def listener(payload: InstanceChangedEvent) -> None:
        actions.append(payload.action)

    event_bus.subscribe(EventType.INSTANCE_CHANGED, listener)
    manager = InstanceManager()
    instance = manager.create("Evented", "1.20.1")
    manager.update(instance, memory_mb=4096)
    manager.select(instance)
    manager.delete(instance)

    assert actions == ["created", "updated", "selected", "deleted"]


def test_metadata_is_json_and_slug_is_safe(flint_home: Path) -> None:
    manager = InstanceManager()
    instance = manager.create("Hello World!", "1.20.1")
    data = json.loads(manager.meta_path(instance).read_text(encoding="utf-8"))
    assert data["name"] == "Hello World!"
    assert data["schema"] == 1
    assert slugify("Hello World!") == "Hello-World"
