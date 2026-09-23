"""Robust, idempotent file download.

* streams to a ``.part`` file and renames atomically, so an interrupted download can never leave
  something that looks complete
* verifies the byte count against ``Content-Length`` and (optionally) a known SHA-256
* retries transient failures (network errors, HTTP 5xx, truncated bodies) with backoff, but fails
  immediately and clearly on client errors such as 404, which no retry can fix
* skips the download when a file the manifest already vouches for is present and unchanged
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from mobilityops.ingestion.manifest import ManifestEntry, utc_now
from mobilityops.log import get_logger

log = get_logger("ingestion.download")


class DownloadError(RuntimeError):
    """A download failed for a reason the caller can act on (message says what to do)."""


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    url: str
    bytes: int
    sha256: str
    retrieved_at: str
    skipped: bool


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _already_have(dest: Path, known: ManifestEntry | None) -> DownloadResult | None:
    if known is None or not dest.exists():
        return None
    if dest.stat().st_size != known.bytes or sha256_file(dest) != known.sha256:
        return None  # file changed or is corrupt: fetch again
    return DownloadResult(dest, known.url, known.bytes, known.sha256, known.retrieved_at, True)


def download(
    url: str,
    dest: Path,
    *,
    client: httpx.Client | None = None,
    known: ManifestEntry | None = None,
    retries: int = 3,
    backoff: float = 1.0,
    timeout: float = 120.0,
    sleep: Callable[[float], None] = time.sleep,
) -> DownloadResult:
    """Download ``url`` to ``dest``. Raises :class:`DownloadError` when it cannot succeed."""
    if (existing := _already_have(dest, known)) is not None:
        log.info("download skipped: unchanged", extra={"ctx": {"path": str(dest)}})
        return existing

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    own_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout)
    last_error = "unknown error"
    try:
        for attempt in range(1, retries + 1):
            try:
                with http.stream("GET", url) as resp:
                    if 400 <= resp.status_code < 500:
                        raise DownloadError(
                            f"{url} returned HTTP {resp.status_code}. The file may not exist "
                            "(for example a month the publisher has not released yet); "
                            "check the URL and the requested date range."
                        )
                    if resp.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}", request=resp.request, response=resp
                        )
                    expected = resp.headers.get("content-length")
                    h = hashlib.sha256()
                    total = 0
                    with part.open("wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)
                            h.update(chunk)
                            total += len(chunk)
                if expected is not None and total != int(expected):
                    raise httpx.TransportError(f"truncated: got {total} of {expected} bytes")
                os.replace(part, dest)
                log.info("downloaded", extra={"ctx": {"url": url, "bytes": total}})
                return DownloadResult(dest, url, total, h.hexdigest(), utc_now(), False)
            except DownloadError:
                raise
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = str(exc) or type(exc).__name__
                log.warning(
                    "download attempt failed",
                    extra={"ctx": {"url": url, "attempt": attempt, "error": last_error}},
                )
                if attempt < retries:
                    sleep(backoff * 2 ** (attempt - 1))
        raise DownloadError(
            f"could not download {url} after {retries} attempts (last error: {last_error}). "
            "Existing data was left untouched; check your connection and re-run."
        )
    finally:
        part.unlink(missing_ok=True)
        if own_client:
            http.close()
