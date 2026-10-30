"""下载器行为：并发、续传、镜像切换、重试与校验。"""

from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path

import httpx
import pytest
import respx
from flint.infra.downloader import DownloadCancelled, Downloader, DownloadError, DownloadTask
from flint.infra.http import HttpClient

URL = "https://cdn.example/file.bin"
MIRROR = "https://mirror.example/file.bin"
PAYLOAD = b"flint-download-test" * 512


@pytest.fixture
def sha1() -> str:
    return hashlib.sha1(PAYLOAD).hexdigest()


def make_downloader(client: HttpClient, **kwargs) -> Downloader:
    return Downloader(
        client, retries=kwargs.pop("retries", 0), backoff=0.0, max_backoff=0.0, **kwargs
    )


async def test_download_writes_file_and_reports_progress(
    tmp_path: Path, http_client: HttpClient, sha1: str
):
    destination = tmp_path / "nested" / "file.bin"
    progress: list[tuple[int, int | None]] = []

    with respx.mock() as mock:
        mock.get(URL).mock(
            return_value=httpx.Response(
                200, content=PAYLOAD, headers={"content-length": str(len(PAYLOAD))}
            )
        )
        result = await make_downloader(http_client).download(
            DownloadTask(URL, destination, sha1=sha1, size=len(PAYLOAD)),
            progress=lambda done, total: progress.append((done, total)),
        )

    assert destination.read_bytes() == PAYLOAD
    assert result.written == len(PAYLOAD)
    assert result.skipped is False
    assert result.attempts == 1
    assert result.source_url == URL
    assert progress[0] == (0, len(PAYLOAD))
    assert progress[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert not (tmp_path / "nested" / "file.bin.part").exists()


async def test_skips_file_that_is_already_complete(
    tmp_path: Path, http_client: HttpClient, sha1: str
):
    destination = tmp_path / "file.bin"
    destination.write_bytes(PAYLOAD)

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL).mock(return_value=httpx.Response(200, content=b"unused"))
        result = await make_downloader(http_client).download(
            DownloadTask(URL, destination, sha1=sha1, size=len(PAYLOAD))
        )

    assert result.skipped is True
    assert route.call_count == 0
    assert destination.read_bytes() == PAYLOAD


async def test_resumes_partial_download(tmp_path: Path, http_client: HttpClient, sha1: str):
    destination = tmp_path / "file.bin"
    part = tmp_path / "file.bin.part"
    offset = 64
    part.write_bytes(PAYLOAD[:offset])

    with respx.mock() as mock:

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["range"] == f"bytes={offset}-"
            return httpx.Response(
                206,
                content=PAYLOAD[offset:],
                headers={
                    "content-length": str(len(PAYLOAD) - offset),
                    "content-range": f"bytes {offset}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}",
                },
            )

        mock.get(URL).mock(side_effect=handler)
        result = await make_downloader(http_client).download(
            DownloadTask(URL, destination, sha1=sha1, size=len(PAYLOAD))
        )

    assert result.resumed is True
    assert destination.read_bytes() == PAYLOAD


async def test_falls_back_to_mirror(tmp_path: Path, http_client: HttpClient, sha1: str):
    destination = tmp_path / "file.bin"

    with respx.mock() as mock:
        mock.get(URL).mock(return_value=httpx.Response(404))
        mock.get(MIRROR).mock(return_value=httpx.Response(200, content=PAYLOAD))
        result = await make_downloader(http_client).download(
            DownloadTask(URL, destination, sha1=sha1, mirrors=(MIRROR,))
        )

    assert result.source_url == MIRROR
    assert destination.read_bytes() == PAYLOAD


async def test_retries_transient_status(tmp_path: Path, http_client: HttpClient, sha1: str):
    destination = tmp_path / "file.bin"

    with respx.mock() as mock:
        route = mock.get(URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, content=PAYLOAD),
            ]
        )
        result = await make_downloader(http_client, retries=2).download(
            DownloadTask(URL, destination, sha1=sha1)
        )

    assert route.call_count == 2
    assert result.attempts == 2
    assert destination.read_bytes() == PAYLOAD


async def test_hash_mismatch_raises_and_removes_partial(tmp_path: Path, http_client: HttpClient):
    destination = tmp_path / "file.bin"

    with respx.mock() as mock:
        mock.get(URL).mock(
            side_effect=[
                httpx.Response(200, content=PAYLOAD),
                httpx.Response(200, content=PAYLOAD),
            ]
        )
        with pytest.raises(DownloadError):
            await make_downloader(http_client, retries=1).download(
                DownloadTask(URL, destination, sha1="0" * 40)
            )

    assert not destination.exists()
    assert not (tmp_path / "file.bin.part").exists()


async def test_cancel_before_start(tmp_path: Path, http_client: HttpClient):
    cancel = threading.Event()
    cancel.set()

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL).mock(return_value=httpx.Response(200, content=PAYLOAD))
        with pytest.raises(DownloadCancelled):
            await make_downloader(http_client).download(
                DownloadTask(URL, tmp_path / "file.bin"), cancel=cancel
            )

    assert route.call_count == 0


async def test_download_all_respects_concurrency_limit(tmp_path: Path, http_client: HttpClient):
    tasks = [DownloadTask(f"{URL}?n={index}", tmp_path / f"file-{index}.bin") for index in range(6)]
    active = 0
    peak = 0
    lock = threading.Lock()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.02)
        with lock:
            active -= 1
        return httpx.Response(200, content=request.url.query)

    with respx.mock() as mock:
        for index in range(6):
            mock.get(f"{URL}?n={index}").mock(side_effect=handler)

        downloader = make_downloader(http_client, max_concurrency=2)
        results = await downloader.download_all(tasks)

    assert len(results) == 6
    assert peak <= 2
    for index in range(6):
        assert (tmp_path / f"file-{index}.bin").read_bytes() == f"n={index}".encode()


async def test_download_all_propagates_cancellation(tmp_path: Path, http_client: HttpClient):
    cancel = threading.Event()
    cancel.set()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(URL).mock(return_value=httpx.Response(200, content=PAYLOAD))
        with pytest.raises(DownloadCancelled):
            await make_downloader(http_client).download_all(
                [DownloadTask(URL, tmp_path / "a.bin"), DownloadTask(URL, tmp_path / "b.bin")],
                cancel=cancel,
            )
