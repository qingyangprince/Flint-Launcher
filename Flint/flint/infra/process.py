"""子进程封装：异步逐行回调、无窗口启动与进程树终止。"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LineCallback = Callable[[str], None]


class ProcessError(Exception):
    """子进程无法启动或异常退出时抛出。"""


class ProcessTimeout(ProcessError):
    """等待进程结束时超时。"""


def _spawn_kwargs() -> dict[str, Any]:
    """批处理式的启动参数：Windows 不弹黑框，POSIX 独立进程组。"""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


@dataclass
class ManagedProcess:
    """已启动的子进程；stdout/stderr 由后台任务逐行转发。"""

    process: asyncio.subprocess.Process
    _pumps: list[asyncio.Task[None]] = field(default_factory=list)

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def running(self) -> bool:
        return self.process.returncode is None

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    async def wait(self) -> int:
        code = await self.process.wait()
        if self._pumps:
            await asyncio.gather(*self._pumps, return_exceptions=True)
        return code

    async def terminate(self, *, grace: float = 5.0) -> int:
        """先礼后兵：先请求退出，超时后连同子进程树一起强杀。"""
        if not self.running:
            return await self.wait()

        if os.name == "nt":
            # Windows 下 game/包装脚本可能派生子进程，直接结束整棵树。
            await _kill_tree(self.pid)
            return await self.wait()

        try:
            self.process.terminate()
        except ProcessLookupError:  # pragma: no cover - 进程已消失
            return await self.wait()

        try:
            return await asyncio.wait_for(self.wait(), timeout=max(grace, 0.1))
        except TimeoutError:
            logger.debug("process %s did not exit in %.1fs, killing group", self.pid, grace)
            await _kill_tree(self.pid)
            return await self.wait()


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


async def start_process(
    command: Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    on_stdout: LineCallback | None = None,
    on_stderr: LineCallback | None = None,
    stdin: int | None = None,
) -> ManagedProcess:
    """启动子进程并立刻返回；输出行通过回调异步送达。"""
    args = [str(part) for part in command]
    if not args:
        raise ProcessError("empty command")

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            stdin=stdin if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_spawn_kwargs(),
        )
    except (OSError, ValueError) as exc:
        raise ProcessError(f"cannot start {args[0]!r}: {exc}") from exc

    managed = ManagedProcess(process)
    if process.stdout is not None:
        managed._pumps.append(asyncio.create_task(_pump(process.stdout, on_stdout)))
    if process.stderr is not None:
        managed._pumps.append(asyncio.create_task(_pump(process.stderr, on_stderr)))
    return managed


async def run_process(
    command: Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    on_stdout: LineCallback | None = None,
    on_stderr: LineCallback | None = None,
    timeout: float | None = None,
    capture: bool = True,
) -> ProcessResult:
    """运行至结束并返回退出码与（可选的）完整输出。"""
    out_lines: list[str] = []
    err_lines: list[str] = []

    def collect(target: list[str], callback: LineCallback | None) -> LineCallback:
        def handler(line: str) -> None:
            if capture:
                target.append(line)
            if callback is not None:
                callback(line)

        return handler

    managed = await start_process(
        command,
        cwd=cwd,
        env=env,
        on_stdout=collect(out_lines, on_stdout),
        on_stderr=collect(err_lines, on_stderr),
    )

    if timeout is None:
        code = await managed.wait()
    else:
        try:
            code = await asyncio.wait_for(managed.wait(), timeout=timeout)
        except TimeoutError as exc:
            await managed.terminate()
            raise ProcessTimeout(f"{command[0]!r} timed out after {timeout:.0f}s") from exc

    return ProcessResult(
        returncode=code,
        stdout="\n".join(out_lines),
        stderr="\n".join(err_lines),
    )


async def _pump(stream: asyncio.StreamReader, callback: LineCallback | None) -> None:
    try:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            if callback is None:
                continue
            try:
                callback(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
            except Exception:  # pragma: no cover - 回调异常不应中断读取
                logger.exception("line callback failed")
    except asyncio.CancelledError:  # pragma: no cover - 关闭阶段
        raise
    except (OSError, ValueError) as exc:  # pragma: no cover - 管道异常
        logger.debug("cannot read subprocess output: %s", exc)


async def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:  # pragma: no cover - 极端环境
            logger.debug("taskkill unavailable: %s", exc)
            return
        await killer.wait()
        return

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError) as exc:  # pragma: no cover
        logger.debug("cannot kill process group %s: %s", pid, exc)
