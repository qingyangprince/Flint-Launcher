"""JRE/JDK 探测、``java -version`` 解析与 Minecraft 版本匹配。"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

JAVA_EXECUTABLE = "java.exe" if os.name == "nt" else "java"
PROBE_TIMEOUT = 10.0

_VERSION_RE = re.compile(r'version\s+"([^"]+)"', re.IGNORECASE)
_OPENJDK_RE = re.compile(r"openjdk\s+([0-9][\w.+-]*)", re.IGNORECASE)
_VENDORS = (
    ("temurin", "Eclipse Temurin"),
    ("adoptium", "Eclipse Temurin"),
    ("adoptopenjdk", "AdoptOpenJDK"),
    ("graalvm", "GraalVM"),
    ("corretto", "Amazon Corretto"),
    ("zulu", "Azul Zulu"),
    ("microsoft", "Microsoft OpenJDK"),
    ("semeru", "IBM Semeru"),
    ("oracle", "Oracle"),
)


class JavaError(Exception):
    """无法探测 Java 或输出无法解析时抛出。"""


@dataclass(frozen=True)
class JavaRuntime:
    """一个可用的 Java 可执行文件。"""

    path: Path
    version: str
    major: int
    vendor: str = ""
    arch: str = ""

    @property
    def label(self) -> str:
        vendor = f" · {self.vendor}" if self.vendor else ""
        return f"Java {self.major} ({self.version}){vendor}"


def parse_java_version(output: str) -> tuple[str, int]:
    """从 ``java -version`` 输出解析 (版本串, 主版本号)。

    兼容 ``java version "1.8.0_381"``、``openjdk version "17.0.8"`` 与
    ``openjdk 21.0.2 2024-01-16`` 等格式。
    """
    if not output or not output.strip():
        raise JavaError("empty java -version output")

    match = _VERSION_RE.search(output) or _OPENJDK_RE.search(output)
    if match is None:
        raise JavaError(f"unrecognised java -version output: {output.strip()[:120]!r}")

    raw = match.group(1).strip()
    parts = re.split(r"[._+-]", raw)
    try:
        if raw.startswith("1.") and len(parts) > 1:
            major = int(parts[1])
        else:
            digits = re.match(r"\d+", raw)
            if digits is None:
                raise ValueError(raw)
            major = int(digits.group(0))
    except ValueError as exc:
        raise JavaError(f"cannot parse java version {raw!r}") from exc
    return raw, major


def detect_vendor(output: str) -> str:
    lowered = output.lower()
    for keyword, name in _VENDORS:
        if keyword in lowered:
            return name
    return "OpenJDK" if "openjdk" in lowered else ""


def probe(path: Path | str) -> JavaRuntime | None:
    """执行 ``<path> -version``；失败时返回 ``None`` 而不是抛异常。"""
    executable = Path(path)
    if executable.is_dir():
        executable = executable / "bin" / JAVA_EXECUTABLE
    if not executable.is_file():
        return None

    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": PROBE_TIMEOUT,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run([str(executable), "-version"], **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("cannot probe java at %s: %s", executable, exc)
        return None

    output = f"{result.stderr}\n{result.stdout}"
    try:
        raw, major = parse_java_version(output)
    except JavaError as exc:
        logger.debug("unparsable java at %s: %s", executable, exc)
        return None
    return JavaRuntime(
        path=executable.resolve(),
        version=raw,
        major=major,
        vendor=detect_vendor(output),
        arch=_current_arch(),
    )


def _current_arch() -> str:
    import platform as _platform

    machine = _platform.machine().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine


def recommend_major(
    mc_version: str, java_version: Mapping[str, Any] | None = None
) -> int:
    """根据 Minecraft 版本推荐 Java 主版本。"""
    if isinstance(java_version, Mapping):
        major = java_version.get("majorVersion")
        if isinstance(major, int) and major > 0:
            return major

    numbers = _parse_mc_version(mc_version)
    if numbers is None:
        return 17
    if numbers >= (1, 20, 5):
        return 21
    if numbers >= (1, 18):
        return 17
    if numbers >= (1, 17):
        return 16
    return 8


def select_runtime(
    runtimes: Iterable[JavaRuntime], recommended: int
) -> JavaRuntime | None:
    """优先选主版本完全匹配的，其次选不低于推荐值的最高版本。"""
    candidates = list(runtimes)
    if not candidates:
        return None
    exact = [runtime for runtime in candidates if runtime.major == recommended]
    if exact:
        return max(exact, key=lambda runtime: runtime.version)
    newer = [runtime for runtime in candidates if runtime.major > recommended]
    if newer:
        return min(newer, key=lambda runtime: runtime.major)
    return max(candidates, key=lambda runtime: runtime.major)


def _parse_mc_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", value or "")
    if match is None:
        return None
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 0),
    )


def candidate_paths() -> list[Path]:
    """各平台常见安装位置的 ``java`` 可执行文件。"""
    found: list[Path] = []

    def add(path: Path | str | None) -> None:
        if not path:
            return
        candidate = Path(path)
        if candidate.is_dir():
            candidate = candidate / "bin" / JAVA_EXECUTABLE
        found.append(candidate)

    add(os.environ.get("JAVA_HOME"))
    which = shutil.which("java")
    if which:
        add(Path(which))

    if os.name == "nt":
        for base in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if not base:
                continue
            root = Path(base)
            for pattern in (
                "Java/*/bin/java.exe",
                "Eclipse Adoptium/*/bin/java.exe",
                "Microsoft/jdk*/bin/java.exe",
                "Zulu/*/bin/java.exe",
                "Amazon Corretto/*/bin/java.exe",
                "Programs/Eclipse Adoptium/*/bin/java.exe",
                "Programs/Microsoft/jdk*/bin/java.exe",
            ):
                found.extend(root.glob(pattern))
    elif sys.platform == "darwin":
        for home in Path("/Library/Java/JavaVirtualMachines").glob(
            "*/Contents/Home/bin/java"
        ):
            found.append(home)
        for home in Path("~/Library/Java/JavaVirtualMachines").expanduser().glob(
            "*/Contents/Home/bin/java"
        ):
            found.append(home)
    else:
        for home in Path("/usr/lib/jvm").glob("*/bin/java"):
            found.append(home)
        found.extend(_update_alternatives())

    unique: list[Path] = []
    seen: set[str] = set()
    for path in found:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _update_alternatives() -> list[Path]:
    if shutil.which("update-alternatives") is None:
        return []
    try:
        result = subprocess.run(
            ["update-alternatives", "--list", "java"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


_cache: list[JavaRuntime] | None = None
_cache_lock = threading.RLock()


def discover(*, refresh: bool = False) -> list[JavaRuntime]:
    """探测所有可用 Java，按主版本从高到低返回（结果带缓存）。"""
    global _cache
    with _cache_lock:
        if _cache is not None and not refresh:
            return list(_cache)
        runtimes: list[JavaRuntime] = []
        seen: set[str] = set()
        for candidate in candidate_paths():
            runtime = probe(candidate)
            if runtime is None:
                continue
            key = str(runtime.path).lower()
            if key in seen:
                continue
            seen.add(key)
            runtimes.append(runtime)
        runtimes.sort(key=lambda runtime: (runtime.major, runtime.version), reverse=True)
        _cache = runtimes
        return list(runtimes)


def reset_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def find_java(
    mc_version: str,
    *,
    java_version: Mapping[str, Any] | None = None,
    preferred: str | None = None,
    runtimes: Sequence[JavaRuntime] | None = None,
) -> JavaRuntime | None:
    """为指定 Minecraft 版本挑选 Java；优先使用显式指定的路径。"""
    if preferred:
        runtime = probe(preferred)
        if runtime is not None:
            return runtime
        logger.warning("configured java path is not usable: %s", preferred)

    available = list(runtimes) if runtimes is not None else discover()
    return select_runtime(available, recommend_major(mc_version, java_version))
