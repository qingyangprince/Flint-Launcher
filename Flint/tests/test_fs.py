"""文件系统基础操作：原子写、原生复制、目录树与取消。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from flint.infra import fs, native_loader
from flint.infra.fs import OperationCancelled

PAYLOAD = b"flint" * 100_000


def test_write_atomic_creates_parents_and_replaces(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "file.json"
    fs.write_atomic(target, '{"a": 1}')
    assert target.read_text(encoding="utf-8") == '{"a": 1}'

    fs.write_atomic(target, b'{"a": 2}')
    assert target.read_bytes() == b'{"a": 2}'
    assert [p.name for p in target.parent.iterdir()] == ["file.json"]


def test_write_atomic_keeps_original_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("no space")

    monkeypatch.setattr("os.fsync", boom)
    with pytest.raises(OSError):
        fs.write_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".file.txt.*.tmp"))


def test_copy_file_python_and_native(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(PAYLOAD)

    python_copy = tmp_path / "python.bin"
    assert fs.copy_file(source, python_copy, use_native=False) == len(PAYLOAD)
    assert python_copy.read_bytes() == PAYLOAD

    native_copy = tmp_path / "native.bin"
    written = fs.copy_file(source, native_copy, use_native=True)
    assert written == len(PAYLOAD)
    assert native_copy.read_bytes() == PAYLOAD


def test_copy_file_handles_non_ascii_names(tmp_path: Path):
    source = tmp_path / "中文来源.bin"
    destination = tmp_path / "子目录" / "副本.bin"
    source.write_bytes(PAYLOAD)

    fs.copy_file(source, destination)

    assert destination.read_bytes() == PAYLOAD


def test_copy_file_honours_cancel(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(PAYLOAD)
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(OperationCancelled):
        fs.copy_file(source, tmp_path / "copy.bin", cancel=cancel)
    assert not (tmp_path / "copy.bin").exists()


def test_copy_file_missing_source(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        fs.copy_file(tmp_path / "missing.bin", tmp_path / "copy.bin")


def test_copy_tree_and_remove(tmp_path: Path):
    source = tmp_path / "src"
    (source / "a" / "b").mkdir(parents=True)
    (source / "root.txt").write_text("root", encoding="utf-8")
    (source / "a" / "b" / "deep.txt").write_text("deep", encoding="utf-8")

    destination = tmp_path / "dst"
    fs.copy_tree(source, destination)

    assert (destination / "root.txt").read_text(encoding="utf-8") == "root"
    assert (destination / "a" / "b" / "deep.txt").read_text(encoding="utf-8") == "deep"

    fs.remove(destination)
    assert not destination.exists()
    fs.remove(destination)  # 默认 missing_ok=True


def test_move_file(tmp_path: Path):
    source = tmp_path / "a.txt"
    source.write_text("a", encoding="utf-8")
    destination = tmp_path / "sub" / "a.txt"

    fs.move(source, destination)

    assert destination.read_text(encoding="utf-8") == "a"
    assert not source.exists()


def test_is_cancelled_accepts_callable_and_rejects_garbage():
    assert fs.is_cancelled(None) is False
    assert fs.is_cancelled(lambda: True) is True
    assert fs.is_cancelled(threading.Event()) is False
    with pytest.raises(TypeError):
        fs.is_cancelled(object())


def test_native_library_optional_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(native_loader, "get_native", lambda **_kwargs: None)
    source = tmp_path / "source.bin"
    source.write_bytes(PAYLOAD)
    assert fs.copy_file(source, tmp_path / "out.bin") == len(PAYLOAD)
