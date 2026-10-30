"""ZIP 解压：正常流程、Zip Slip 拦截、取消与回退。"""

from __future__ import annotations

import threading
import zipfile
from pathlib import Path

import pytest
from flint.infra import extract as extract_module
from flint.infra import native_loader
from flint.infra.extract import (
    ExtractionCancelled,
    ExtractionError,
    extract_zip,
    is_safe_member,
    list_members,
    target_path,
)


def build_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return path


def test_is_safe_member_rules():
    assert is_safe_member("assets/icon.png")
    assert is_safe_member("a/./b.txt")
    assert not is_safe_member("../evil.txt")
    assert not is_safe_member("a/../../evil.txt")
    assert not is_safe_member("/etc/passwd")
    assert not is_safe_member("\\windows\\system32")
    assert not is_safe_member("C:/Windows/notepad.exe")
    assert not is_safe_member("")


def test_target_path_rejects_escape(tmp_path: Path):
    assert target_path(tmp_path, "nested/file.txt") == (tmp_path / "nested" / "file.txt").resolve()
    with pytest.raises(ExtractionError):
        target_path(tmp_path, "../escape.txt")


def test_extracts_nested_entries(tmp_path: Path):
    archive = build_zip(
        tmp_path / "archive.zip",
        {
            "manifest.json": b'{"ok": true}',
            "assets/lang/en_us.json": b"{}",
            "assets/empty.txt": b"",
        },
    )
    destination = tmp_path / "out"

    extract_zip(archive, destination)

    assert (destination / "manifest.json").read_bytes() == b'{"ok": true}'
    assert (destination / "assets" / "lang" / "en_us.json").read_bytes() == b"{}"
    assert (destination / "assets" / "empty.txt").read_bytes() == b""
    assert sorted(list_members(archive)) == [
        "assets/empty.txt",
        "assets/lang/en_us.json",
        "manifest.json",
    ]


def test_extracts_non_ascii_paths(tmp_path: Path):
    archive = build_zip(
        tmp_path / "归档.zip",
        {"资源/说明.txt": "中文内容".encode()},
    )
    destination = tmp_path / "输出"

    extract_zip(archive, destination)

    assert (destination / "资源" / "说明.txt").read_text(encoding="utf-8") == "中文内容"


def test_python_fallback_extracts_nested_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(native_loader, "get_native", lambda **_kwargs: None)
    archive = build_zip(tmp_path / "archive.zip", {"a/b/c.txt": b"c"})
    destination = tmp_path / "out"

    extract_zip(archive, destination)

    assert (destination / "a" / "b" / "c.txt").read_bytes() == b"c"


def test_zip_slip_is_rejected(tmp_path: Path):
    archive = build_zip(tmp_path / "evil.zip", {"../escaped.txt": b"owned"})
    destination = tmp_path / "out"

    with pytest.raises(ExtractionError):
        extract_zip(archive, destination)

    assert not (tmp_path / "escaped.txt").exists()
    assert not (destination / "escaped.txt").exists()


def test_absolute_member_is_rejected(tmp_path: Path):
    archive = build_zip(tmp_path / "evil.zip", {"/absolute.txt": b"owned"})
    with pytest.raises(ExtractionError):
        extract_zip(archive, tmp_path / "out")


def test_cancel_before_start(tmp_path: Path):
    archive = build_zip(tmp_path / "archive.zip", {"a.txt": b"a"})
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(ExtractionCancelled):
        extract_zip(archive, tmp_path / "out", cancel=cancel)

    assert not (tmp_path / "out" / "a.txt").exists()


def test_cancel_with_callable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(native_loader, "get_native", lambda **_kwargs: None)
    archive = build_zip(tmp_path / "archive.zip", {"a.txt": b"a"})

    with pytest.raises(ExtractionCancelled):
        extract_zip(archive, tmp_path / "out", cancel=lambda: True)


def test_invalid_archive_raises(tmp_path: Path):
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"this is not a zip file")
    with pytest.raises(ExtractionError):
        extract_zip(broken, tmp_path / "out", use_native=False)


def test_missing_archive_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        extract_zip(tmp_path / "missing.zip", tmp_path / "out")


def test_native_cancellation_maps_to_extraction_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = build_zip(tmp_path / "archive.zip", {"a.txt": b"a"})

    fake = type(
        "FakeNative",
        (),
        {
            "extract_zip": lambda self, *_args, **_kwargs: (_ for _ in ()).throw(
                native_loader.NativeCancelled(
                    "cancelled",
                    code=native_loader.FLINT_ERR_CANCELLED,
                    function="flint_extract_zip",
                )
            )
        },
    )()

    monkeypatch.setattr(extract_module.native_loader, "get_native", lambda **_kwargs: fake)

    with pytest.raises(ExtractionCancelled):
        extract_zip(archive, tmp_path / "out")
