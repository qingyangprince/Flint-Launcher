"""面向 manifest 与版本 JSON 的 ETag / Last-Modified 缓存。"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flint.infra import fs, http
from flint.platform import paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheEntry:
    url: str
    content: bytes
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    fetched_at: float = 0.0

    def text(self, encoding: str = "utf-8") -> str:
        return self.content.decode(encoding)

    def json(self) -> Any:
        return json.loads(self.content)


@dataclass(frozen=True)
class CacheResult:
    content: bytes
    from_cache: bool
    etag: str | None = None
    last_modified: str | None = None
    status_code: int = 200

    def json(self) -> Any:
        return json.loads(self.content)


class HttpCache:
    """每个 URL 保存一份元数据文件与一份正文文件。"""

    def __init__(self, directory: Path | str | None = None) -> None:
        self._directory = Path(directory) if directory is not None else paths.http_cache_dir()

    @property
    def directory(self) -> Path:
        return self._directory

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = self._key(url)
        return self._directory / f"{key}.meta.json", self._directory / f"{key}.body"

    def get(self, url: str) -> CacheEntry | None:
        meta_path, body_path = self._paths(url)
        if not meta_path.is_file() or not body_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            content = body_path.read_bytes()
        except (OSError, ValueError) as exc:
            logger.warning("discarding unreadable cache entry for %s: %s", url, exc)
            self.remove(url)
            return None
        return CacheEntry(
            url=meta.get("url", url),
            content=content,
            etag=meta.get("etag"),
            last_modified=meta.get("last_modified"),
            content_type=meta.get("content_type"),
            fetched_at=float(meta.get("fetched_at", 0.0)),
        )

    def set(
        self,
        url: str,
        *,
        content: bytes,
        etag: str | None = None,
        last_modified: str | None = None,
        content_type: str | None = None,
    ) -> CacheEntry:
        meta_path, body_path = self._paths(url)
        fs.ensure_dir(self._directory)
        fs.write_atomic(body_path, content)
        meta = {
            "url": url,
            "etag": etag,
            "last_modified": last_modified,
            "content_type": content_type,
            "fetched_at": time.time(),
            "size": len(content),
        }
        fs.write_atomic(meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        return CacheEntry(
            url=url,
            content=content,
            etag=etag,
            last_modified=last_modified,
            content_type=content_type,
            fetched_at=meta["fetched_at"],
        )

    def remove(self, url: str) -> None:
        for path in self._paths(url):
            path.unlink(missing_ok=True)

    def clear(self) -> None:
        if not self._directory.is_dir():
            return
        for path in self._directory.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)

    async def fetch(
        self,
        client: http.HttpClient,
        url: str,
        *,
        max_age: float = 0.0,
        force: bool = False,
        headers: dict[str, str] | None = None,
        retries: int | None = None,
    ) -> CacheResult:
        """返回 ``url`` 的正文，命中缓存时带 ``If-None-Match`` 做条件请求。

        当缓存年龄小于 ``max_age`` 秒时直接复用缓存，不发起任何网络请求。
        """
        entry = None if force else self.get(url)
        if entry is not None and max_age > 0 and (time.time() - entry.fetched_at) < max_age:
            return CacheResult(
                content=entry.content,
                from_cache=True,
                etag=entry.etag,
                last_modified=entry.last_modified,
            )

        request_headers = dict(headers or {})
        if entry is not None and not force:
            if entry.etag:
                request_headers["If-None-Match"] = entry.etag
            elif entry.last_modified:
                request_headers["If-Modified-Since"] = entry.last_modified

        try:
            response = await client.get(url, headers=request_headers, retries=retries)
        except http.HttpError as exc:
            if entry is not None:
                logger.warning("using stale cache for %s after %s", url, exc)
                return CacheResult(
                    content=entry.content,
                    from_cache=True,
                    etag=entry.etag,
                    last_modified=entry.last_modified,
                    status_code=exc.status_code or 0,
                )
            raise

        status = response.status_code
        if status == 304 and entry is not None:
            content = entry.content
            await response.aclose()
            self.set(
                url,
                content=content,
                etag=response.headers.get("etag", entry.etag),
                last_modified=response.headers.get("last-modified", entry.last_modified),
                content_type=entry.content_type,
            )
            return CacheResult(
                content=content,
                from_cache=True,
                etag=entry.etag,
                last_modified=entry.last_modified,
                status_code=status,
            )

        content = response.content
        saved = self.set(
            url,
            content=content,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            content_type=response.headers.get("content-type"),
        )
        await response.aclose()
        return CacheResult(
            content=content,
            from_cache=False,
            etag=saved.etag,
            last_modified=saved.last_modified,
            status_code=status,
        )

    async def fetch_json(
        self,
        client: http.HttpClient,
        url: str,
        *,
        max_age: float = 0.0,
        force: bool = False,
        headers: dict[str, str] | None = None,
        retries: int | None = None,
    ) -> Any:
        result = await self.fetch(
            client, url, max_age=max_age, force=force, headers=headers, retries=retries
        )
        try:
            return result.json()
        except ValueError as exc:
            raise http.HttpError(
                f"cached response for {url} is not valid JSON: {exc}", url=url
            ) from exc


def default_cache() -> HttpCache:
    return HttpCache()
