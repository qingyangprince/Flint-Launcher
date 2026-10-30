"""统一的 ``httpx`` 客户端：超时、代理、UA 与重试/退避。"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from flint import __version__

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 0.5
MAX_BACKOFF = 8.0
DEFAULT_USER_AGENT = f"Flint/{__version__} (+https://github.com/flint-launcher/flint)"

RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_TRANSPORT_ERRORS = (httpx.TransportError, httpx.TimeoutException)


class HttpError(Exception):
    """请求最终失败时抛出（状态码不可重试或重试次数耗尽）。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
        body: str | None = None,
        retries: int = 0,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.body = body
        self.retries = retries


class HttpClient:
    """自带重试的异步 HTTP 客户端。

    ``stream`` 刻意不做重试：断点续传和镜像切换由下载器负责，
    因为只有它了解已写入的部分文件状态。
    """

    def __init__(
        self,
        *,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        max_backoff: float = MAX_BACKOFF,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        follow_redirects: bool = True,
        trust_env: bool = True,
    ) -> None:
        self.retries = max(int(retries), 0)
        self.backoff = max(float(backoff), 0.0)
        self.max_backoff = max(float(max_backoff), 0.0)

        merged_headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
        if headers:
            merged_headers.update(headers)

        timeout_config = (
            httpx.Timeout(timeout, connect=min(float(timeout), 10.0))
            if isinstance(timeout, (int, float))
            else timeout
        )
        client_kwargs: dict[str, Any] = {
            "timeout": timeout_config,
            "headers": merged_headers,
            "transport": transport,
            "follow_redirects": follow_redirects,
            "trust_env": trust_env,
        }
        if proxy:
            client_kwargs["proxy"] = proxy

        self._client = httpx.AsyncClient(**client_kwargs)
        self._closed = False

    @property
    def raw(self) -> httpx.AsyncClient:
        return self._client

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(max(float(retry_after), 0.0), self.max_backoff)
                except ValueError:
                    pass
        return min(self.backoff * (2**attempt), self.max_backoff)

    async def request(
        self,
        method: str,
        url: str,
        *,
        retries: int | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        attempts = (self.retries if retries is None else max(int(retries), 0)) + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await self._client.request(method, url, **kwargs)
            except _TRANSPORT_ERRORS as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    delay = self._delay(attempt, None)
                    logger.debug("%s %s failed (%s), retrying in %.2fs", method, url, exc, delay)
                    await asyncio.sleep(delay)
                    continue
                break

            if response.status_code in RETRY_STATUS and attempt + 1 < attempts:
                delay = self._delay(attempt, response)
                await response.aclose()
                logger.debug(
                    "%s %s returned %d, retrying in %.2fs",
                    method,
                    url,
                    response.status_code,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code >= 400:
                body = _safe_body(response)
                await response.aclose()
                raise HttpError(
                    f"{method} {url} returned HTTP {response.status_code}",
                    status_code=response.status_code,
                    url=url,
                    body=body,
                    retries=attempt,
                )
            return response

        raise HttpError(
            f"{method} {url} failed after {attempts} attempt(s): {last_error}",
            url=url,
            retries=attempts - 1,
        )

    async def get(self, url: str, *, retries: int | None = None, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, retries=retries, **kwargs)

    async def get_json(self, url: str, *, retries: int | None = None, **kwargs: Any) -> Any:
        response = await self.get(url, retries=retries, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise HttpError(
                f"GET {url} did not return valid JSON: {exc}",
                status_code=response.status_code,
                url=url,
            ) from exc
        finally:
            await response.aclose()

    @asynccontextmanager
    async def stream(self, method: str, url: str, **kwargs: Any) -> AsyncIterator[httpx.Response]:
        request = self._client.build_request(method, url, **kwargs)
        response = await self._client.send(request, stream=True)
        try:
            yield response
        finally:
            await response.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._client.aclose()

    close = aclose

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def _safe_body(response: httpx.Response) -> str:
    try:
        return response.text[:400]
    except Exception:  # pragma: no cover - 仅用于诊断信息
        return ""


_lock = threading.RLock()
_client: HttpClient | None = None


def create_client(**kwargs: Any) -> HttpClient:
    return HttpClient(**kwargs)


def get_client() -> HttpClient:
    """返回进程级客户端单例（首次调用时创建）。"""
    global _client
    with _lock:
        if _client is None:
            _client = HttpClient()
        return _client


def set_client(client: HttpClient | None) -> None:
    """替换单例（测试用，或用户修改代理设置后重建）。"""
    global _client
    with _lock:
        _client = client


async def close_client() -> None:
    global _client
    with _lock:
        client, _client = _client, None
    if client is not None:
        await client.aclose()
