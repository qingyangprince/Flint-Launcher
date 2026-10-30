"""哈希：原生与纯 Python 结果一致性、分块流式读取与回退行为。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flint.infra import hash as hashing
from flint.infra import native_loader


def write_sample(path: Path, size: int = 3 * 1024 * 1024 + 123) -> Path:
    block = bytes(range(256)) * 4
    with path.open("wb") as handle:
        remaining = size
        while remaining > 0:
            chunk = block[: min(len(block), remaining)]
            handle.write(chunk)
            remaining -= len(chunk)
    return path


@pytest.mark.parametrize("algo", ["sha1", "sha256"])
def test_native_matches_hashlib(tmp_path: Path, algo: str):
    native = native_loader.get_native()
    if native is None:
        pytest.skip(f"native library unavailable: {native_loader.unavailable_reason()}")

    sample = write_sample(tmp_path / "sample.bin")
    expected = hashlib.new(algo, sample.read_bytes()).hexdigest()

    assert hashing.hash_file(sample, algo) == expected
    assert hashing.hash_file(sample, algo, use_native=False) == expected


@pytest.mark.parametrize("algo", ["sha1", "sha256"])
def test_python_fallback_matches_hashlib(tmp_path: Path, algo: str):
    sample = write_sample(tmp_path / "sample.bin", size=700_000)
    expected = hashlib.new(algo, sample.read_bytes()).hexdigest()
    assert hashing.hash_file(sample, algo, chunk_size=4096, use_native=False) == expected


def test_hash_bytes_and_normalize():
    assert hashing.hash_bytes(b"flint", "SHA-1") == hashlib.sha1(b"flint").hexdigest()
    assert hashing.hash_bytes(b"flint", "sha256") == hashlib.sha256(b"flint").hexdigest()
    with pytest.raises(ValueError):
        hashing.normalize_algo("md5")


def test_hash_file_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        hashing.hash_file(tmp_path / "nope.bin")


def test_hash_file_with_non_ascii_path(tmp_path: Path):
    sample = tmp_path / "中文文件.bin"
    sample.write_bytes(b"flint-native")
    expected = hashlib.sha256(b"flint-native").hexdigest()
    assert hashing.hash_file(sample, "sha256") == expected


def test_verify_file(tmp_path: Path):
    sample = write_sample(tmp_path / "sample.bin", size=1024)
    digest = hashlib.sha1(sample.read_bytes()).hexdigest()
    assert hashing.verify_file(sample, digest)
    assert hashing.verify_file(sample, digest.upper())
    assert not hashing.verify_file(sample, "0" * 40)
    assert not hashing.verify_file(tmp_path / "missing.bin", digest)


def test_native_failure_falls_back_to_hashlib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sample = write_sample(tmp_path / "sample.bin", size=2048)
    expected = hashlib.sha1(sample.read_bytes()).hexdigest()

    broken = MagicMock()
    broken.hash_file.side_effect = native_loader.NativeCallError(
        "boom", code=native_loader.FLINT_ERR_IO, function="flint_hash_file"
    )
    monkeypatch.setattr(native_loader, "get_native", lambda **_kwargs: broken)

    assert hashing.hash_file(sample, "sha1") == expected
    broken.hash_file.assert_called_once()
