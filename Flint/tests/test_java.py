"""``java -version`` 解析、版本推荐与运行时选择。"""

from __future__ import annotations

from pathlib import Path

import pytest
from flint.platform import java


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ('java version "1.8.0_381"', ("1.8.0_381", 8)),
        ('openjdk version "17.0.8" 2023-07-18', ("17.0.8", 17)),
        ('openjdk version "21.0.2" 2024-01-16 LTS', ("21.0.2", 21)),
        ("openjdk 11.0.21 2023-10-17", ("11.0.21", 11)),
    ],
)
def test_parse_java_version(output: str, expected: tuple[str, int]) -> None:
    assert java.parse_java_version(output) == expected


def test_parse_java_version_rejects_garbage() -> None:
    with pytest.raises(java.JavaError):
        java.parse_java_version("not a java version")


@pytest.mark.parametrize(
    ("mc_version", "expected"),
    [
        ("1.12.2", 8),
        ("1.16.5", 8),
        ("1.17.1", 16),
        ("1.18.2", 17),
        ("1.20.4", 17),
        ("1.20.5", 21),
        ("1.21.4", 21),
    ],
)
def test_recommend_major(mc_version: str, expected: int) -> None:
    assert java.recommend_major(mc_version) == expected


def test_recommend_major_prefers_version_json() -> None:
    assert java.recommend_major("1.20.1", {"majorVersion": 8}) == 8


def test_select_runtime_prefers_exact_match() -> None:
    runtimes = [
        java.JavaRuntime(path=Path("a"), version="8.0.1", major=8),
        java.JavaRuntime(path=Path("b"), version="17.0.8", major=17),
        java.JavaRuntime(path=Path("c"), version="21.0.2", major=21),
    ]
    assert java.select_runtime(runtimes, 17).path == Path("b")
    assert java.select_runtime(runtimes, 16).path == Path("b")  # 最接近的更高版本
    assert java.select_runtime(runtimes, 25).path == Path("c")  # 没有更高版本时取最高
    assert java.select_runtime([], 17) is None


def test_detect_vendor() -> None:
    assert java.detect_vendor('OpenJDK Runtime Environment Temurin-17') == "Eclipse Temurin"
    assert java.detect_vendor('java version "1.8.0" Oracle') == "Oracle"
    assert java.detect_vendor('openjdk version "17"') == "OpenJDK"
    assert java.detect_vendor("unknown") == ""


def test_probe_missing_path(tmp_path: Path) -> None:
    assert java.probe(tmp_path / "missing-java") is None
