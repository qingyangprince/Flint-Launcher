"""并发、可续传的下载器：镜像切换、重试与哈希校验。"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from flint.infra import fs, http
from flint.infra import hash as hashing

logger = logging.getLogger(__name__)

PART_SUFFIX = ".part"
DEFAULT_CHUNK_SIZE = 64 * 1024
DEFAULT_CONCURRENCY = 8

ProgressCallback = Callable[[int, int | None], None]
AllProgressCallback = Callable[["DownloadTask", int, int | None], None]


class DownloadError(Exception):
    """下载无法完成时抛出。"""


class DownloadCancelled(DownloadError):
    """取消令牌中止传输时抛出。"""


class _RetryableDownload(DownloadError):
    """内部标记：这类失败值得重试。"""


@dataclass(frozen=True)
class DownloadTask:
    url: str
    dest: Path
    sha1: str | None = None
    size: int | None = None
    mirrors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dest", Path(self.dest))
        object.__setattr__(self, "mirrors", tuple(self.mirrors))

    @property
    def candidates(self) -> tuple[str, ...]:
        ordered = (self.url, *self.mirrors)
        return tuple(dict.fromkeys(ordered))

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> DownloadTask:
        return cls(
            url=data["url"],
            dest=Path(data["dest"]),
            sha1=data.get("sha1"),
            size=data.get("size"),
            mirrors=tuple(data.get("mirrors") or ()),
        )


@dataclass(frozen=True)
class DownloadResult:
    task: DownloadTask
    written: int
    skipped: bool = False
    attempts: int = 0
    source_url: str = ""
    resumed: bool = False


@dataclass
class _Transfer:
    written: int
    resumed: bool
    source_url: str


class Downloader:
    def __init__(
        self,
        client: http.HttpClient | None = None,
        *,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        retries: int = 3,
        backoff: float = 0.5,
        max_backoff: float = 8.0,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        self.retries = max(int(retries), 0)
        self.backoff = max(float(backoff), 0.0)
        self.max_backoff = max(float(max_backoff), 0.0)
        self.chunk_size = max(int(chunk_size), 1024)
        self._client = client
        self._semaphore = asyncio.Semaphore(max(int(max_concurrency), 1))

    @property
    def client(self) -> http.HttpClient:
        if self._client is None:
            self._client = http.get_client()
        return self._client

    def _delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(max(float(retry_after), 0.0), self.max_backoff)
                except ValueError:
                    pass
        return min(self.backoff * (2**attempt), self.max_backoff)

    async def download(
        self,
        task: DownloadTask,
        *,
        progress: ProgressCallback | None = None,
        cancel: object = None,
    ) -> DownloadResult:
        if not isinstance(task, DownloadTask):
            task = DownloadTask.from_mapping(task)

        dest = task.dest
        if fs.is_cancelled(cancel):
            raise DownloadCancelled(f"download cancelled before start: {task.url}")
        if dest.is_file() and self._is_complete(dest, task):
            logger.debug("skipping already complete download: %s", dest)
            return DownloadResult(
                task=task, written=dest.stat().st_size, skipped=True, source_url=task.url
            )

        fs.ensure_parent(dest)
        part = dest.with_name(dest.name + PART_SUFFIX)
        attempts = 0
        last_error: Exception | None = None

        async with self._semaphore:
            for url in task.candidates:
                if fs.is_cancelled(cancel):
                    raise DownloadCancelled(f"download cancelled: {task.url}")
                for attempt in range(self.retries + 1):
                    attempts += 1
                    try:
                        transfer = await self._transfer(url, task, part, progress, cancel)
                    except DownloadCancelled:
                        raise
                    except _RetryableDownload as exc:
                        last_error = exc
                        if attempt < self.retries:
                            delay = self._delay(attempt)
                            logger.debug("retrying %s in %.2fs: %s", url, delay, exc)
                            await asyncio.sleep(delay)
                        continue
                    except http.HttpError as exc:
                        last_error = exc
                        if exc.status_code in http.RETRY_STATUS and attempt < self.retries:
                            await asyncio.sleep(self._delay(attempt))
                            continue
                        break
                    except (httpx.TransportError, httpx.TimeoutException) as exc:
                        last_error = exc
                        if attempt < self.retries:
                            await asyncio.sleep(self._delay(attempt))
                            continue
                        break
                    else:
                        os.replace(part, dest)
                        return DownloadResult(
                            task=task,
                            written=transfer.written,
                            skipped=False,
                            attempts=attempts,
                            source_url=transfer.source_url,
                            resumed=transfer.resumed,
                        )

        # 保留未完成的 .part 文件，供下次运行续传。
        raise DownloadError(f"failed to download {task.url}: {last_error}") from last_error

    async def download_all(
        self,
        tasks: Sequence[DownloadTask] | Iterable[DownloadTask],
        *,
        progress: AllProgressCallback | None = None,
        cancel: object = None,
    ) -> list[DownloadResult]:
        task_list = [
            t if isinstance(t, DownloadTask) else DownloadTask.from_mapping(t) for t in tasks
        ]

        async def run(task: DownloadTask) -> DownloadResult:
            callback = (lambda done, total: progress(task, done, total)) if progress else None
            return await self.download(task, progress=callback, cancel=cancel)

        return list(await asyncio.gather(*(run(task) for task in task_list)))

    def _is_complete(self, path: Path, task: DownloadTask) -> bool:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if task.size is not None and size != task.size:
            return False
        if task.sha1:
            try:
                return hashing.verify_file(path, task.sha1, "sha1")
            except OSError:
                return False
        return True

    async def _transfer(
        self,
        url: str,
        task: DownloadTask,
        part: Path,
        progress: ProgressCallback | None,
        cancel: object,
    ) -> _Transfer:
        offset = part.stat().st_size if part.is_file() else 0
        if task.size is not None and offset > task.size:
            part.unlink(missing_ok=True)
            offset = 0

        headers: dict[str, str] = {}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        async with self.client.stream("GET", url, headers=headers) as response:
            status = response.status_code
            if status == 416:
                part.unlink(missing_ok=True)
                raise _RetryableDownload(f"server rejected resume range for {url}")

            if status >= 400:
                body = await _read_error_body(response)
                raise http.HttpError(
                    f"GET {url} returned HTTP {status}",
                    status_code=status,
                    url=url,
                    body=body,
                )

            if offset and status == 200:
                logger.debug("server ignored Range for %s; restarting from scratch", url)
                offset = 0
            elif offset and status == 206:
                expected_start = self._content_range_start(response.headers.get("content-range"))
                if expected_start is not None and expected_start != offset:
                    part.unlink(missing_ok=True)
                    raise _RetryableDownload(
                        f"unexpected Content-Range start {expected_start} for {url} (wanted {offset})"
                    )

            resumed = offset > 0 and status == 206
            total = self._total_size(response, task, offset, resumed)
            written = offset
            mode = "ab" if resumed else "wb"

            if progress is not None:
                progress(written, total)

            with part.open(mode) as handle:
                async for chunk in response.aiter_bytes(self.chunk_size):
                    if fs.is_cancelled(cancel):
                        raise DownloadCancelled(f"download cancelled: {url}")
                    handle.write(chunk)
                    written += len(chunk)
                    if progress is not None:
                        progress(written, total)
                handle.flush()
                os.fsync(handle.fileno())

        if task.sha1:
            actual = hashing.hash_file(part, "sha1")
            if actual.lower() != task.sha1.strip().lower():
                part.unlink(missing_ok=True)
                raise _RetryableDownload(
                    f"sha1 mismatch for {url}: expected {task.sha1}, got {actual}"
                )

        if task.size is not None and part.stat().st_size != task.size:
            actual_size = part.stat().st_size
            part.unlink(missing_ok=True)
            raise _RetryableDownload(
                f"size mismatch for {url}: expected {task.size}, got {actual_size}"
            )

        return _Transfer(written=written, resumed=resumed, source_url=url)

    @staticmethod
    def _content_range_start(value: str | None) -> int | None:
        if not value:
            return None
        try:
            return int(value.split()[1].split("-")[0])
        except (IndexError, ValueError):
            return None

    @staticmethod
    def _total_size(
        response: httpx.Response, task: DownloadTask, offset: int, resumed: bool
    ) -> int | None:
        content_range = response.headers.get("content-range")
        if content_range and "/" in content_range:
            try:
                total = int(content_range.rsplit("/", 1)[1])
                if total >= 0:
                    return total
            except ValueError:
                pass
        length = response.headers.get("content-length")
        if length:
            try:
                remaining = int(length)
            except ValueError:
                remaining = None
            if remaining is not None:
                return offset + remaining if resumed else remaining
        return task.size


async def _read_error_body(response: httpx.Response) -> str | None:
    try:
        await response.aread()
        return response.text[:200]
    except Exception:  # pragma: no cover - diagnostics only
        return None
