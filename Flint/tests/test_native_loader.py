"""原生库加载器：库缺失、ABI 不匹配、成功路径与错误码映射。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flint.infra import native_loader


@pytest.fixture(autouse=True)
def reset_loader():
    native_loader.reset_cache()
    yield
    native_loader.reset_cache()


def fake_library(tmp_path: Path, abi: int) -> MagicMock:
    library = MagicMock(name="flint_native")
    library.flint_abi_version.return_value = abi
    library.flint_last_error.return_value = b""
    return library


def test_missing_library_is_graceful(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(native_loader, "_candidate_paths", lambda: iter(()))
    assert native_loader.get_native() is None
    assert native_loader.is_available() is False
    assert "no flint_native library found" in (native_loader.unavailable_reason() or "")


def test_abi_mismatch_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = tmp_path / "flint_native.dll"
    candidate.write_bytes(b"not really a library")
    monkeypatch.setattr(native_loader, "_candidate_paths", lambda: iter([candidate]))
    monkeypatch.setattr(
        native_loader.ctypes, "CDLL", lambda *_args, **_kwargs: fake_library(tmp_path, 99)
    )

    assert native_loader.get_native() is None
    reason = native_loader.unavailable_reason() or ""
    assert "ABI mismatch" in reason
    assert "99" in reason


def test_load_failure_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = tmp_path / "flint_native.dll"
    candidate.write_bytes(b"broken")

    def explode(*_args, **_kwargs):
        raise OSError("invalid ELF header")

    monkeypatch.setattr(native_loader, "_candidate_paths", lambda: iter([candidate]))
    monkeypatch.setattr(native_loader.ctypes, "CDLL", explode)

    assert native_loader.get_native() is None
    assert "invalid ELF header" in (native_loader.unavailable_reason() or "")


def test_successful_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = tmp_path / "flint_native.dll"
    candidate.write_bytes(b"stub")
    library = fake_library(tmp_path, native_loader.FLINT_NATIVE_ABI_VERSION)
    monkeypatch.setattr(native_loader, "_candidate_paths", lambda: iter([candidate]))
    monkeypatch.setattr(native_loader.ctypes, "CDLL", lambda *_args, **_kwargs: library)

    loaded = native_loader.get_native()

    assert loaded is not None
    assert loaded.abi_version == native_loader.FLINT_NATIVE_ABI_VERSION
    assert loaded.path == candidate
    assert native_loader.get_native() is loaded  # 已缓存


def test_native_error_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = tmp_path / "flint_native.dll"
    candidate.write_bytes(b"stub")
    library = fake_library(tmp_path, native_loader.FLINT_NATIVE_ABI_VERSION)
    library.flint_hash_file.return_value = native_loader.FLINT_ERR_IO
    library.flint_last_error.return_value = b"disk on fire"
    monkeypatch.setattr(native_loader, "_candidate_paths", lambda: iter([candidate]))
    monkeypatch.setattr(native_loader.ctypes, "CDLL", lambda *_args, **_kwargs: library)

    loaded = native_loader.get_native()
    assert loaded is not None

    with pytest.raises(native_loader.NativeCallError) as info:
        loaded.hash_file(tmp_path / "whatever.bin", "sha1")
    assert "disk on fire" in str(info.value)
    assert info.value.code == native_loader.FLINT_ERR_IO

    library.flint_extract_zip.return_value = native_loader.FLINT_ERR_CANCELLED
    with pytest.raises(native_loader.NativeCancelled):
        loaded.extract_zip(tmp_path / "a.zip", tmp_path / "out")


def test_real_library_reports_expected_abi():
    loaded = native_loader.get_native()
    if loaded is None:
        pytest.skip(f"native library not built: {native_loader.unavailable_reason()}")
    assert loaded.abi_version == native_loader.FLINT_NATIVE_ABI_VERSION
    assert loaded.hash_file.__self__ is loaded
