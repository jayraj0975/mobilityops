from pathlib import Path

import httpx
import pytest

from mobilityops.ingestion.download import DownloadError, download, sha256_file
from mobilityops.ingestion.manifest import Manifest, ManifestEntry, utc_now

BODY = b"x" * 5000


def client_for(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_successful_download_is_verified_and_atomic(tmp_path: Path) -> None:
    dest = tmp_path / "a" / "file.bin"
    c = client_for(lambda r: httpx.Response(200, content=BODY, headers={"content-length": "5000"}))
    res = download("https://x/f", dest, client=c)
    assert dest.read_bytes() == BODY
    assert res.bytes == 5000 and res.sha256 == sha256_file(dest) and not res.skipped
    assert not list(dest.parent.glob("*.part"))  # no partial file left behind


def test_client_error_fails_immediately_without_retrying(tmp_path: Path) -> None:
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(DownloadError, match=r"HTTP 404.*may not exist"):
        download(
            "https://x/missing", tmp_path / "m", client=client_for(handler), sleep=lambda s: None
        )
    assert len(calls) == 1  # a 404 cannot be fixed by retrying
    assert not (tmp_path / "m").exists()


def test_transient_server_error_is_retried_with_backoff(tmp_path: Path) -> None:
    attempts = {"n": 0}
    sleeps: list[float] = []

    def handler(r: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=BODY)

    res = download(
        "https://x/f", tmp_path / "f", client=client_for(handler), backoff=1.0, sleep=sleeps.append
    )
    assert attempts["n"] == 3 and res.bytes == 5000
    assert sleeps == [1.0, 2.0]  # exponential backoff


def test_persistent_failure_raises_and_leaves_existing_data_untouched(tmp_path: Path) -> None:
    dest = tmp_path / "f"
    dest.write_bytes(b"good existing data")
    c = client_for(lambda r: httpx.Response(500))
    with pytest.raises(DownloadError, match="left untouched"):
        download("https://x/f", dest, client=c, retries=2, sleep=lambda s: None)
    assert dest.read_bytes() == b"good existing data"
    assert not list(tmp_path.glob("*.part"))


def test_truncated_body_is_detected(tmp_path: Path) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"short", headers={"content-length": "100"})

    with pytest.raises(DownloadError):
        download(
            "https://x/f",
            tmp_path / "f",
            client=client_for(handler),
            retries=2,
            sleep=lambda s: None,
        )
    assert not (tmp_path / "f").exists()


def test_unchanged_file_is_skipped_without_any_network_call(tmp_path: Path) -> None:
    dest = tmp_path / "f"
    dest.write_bytes(BODY)
    known = ManifestEntry("s", "https://x/f", "f", 5000, sha256_file(dest), utc_now())

    def boom(r: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be touched for an unchanged file")

    res = download("https://x/f", dest, client=client_for(boom), known=known)
    assert res.skipped


def test_changed_or_corrupt_file_is_downloaded_again(tmp_path: Path) -> None:
    dest = tmp_path / "f"
    dest.write_bytes(BODY)
    known = ManifestEntry("s", "https://x/f", "f", 5000, sha256_file(dest), utc_now())
    dest.write_bytes(b"y" * 5000)  # same size, different content -> hash mismatch
    c = client_for(lambda r: httpx.Response(200, content=BODY))
    res = download("https://x/f", dest, client=c, known=known)
    assert not res.skipped and dest.read_bytes() == BODY


def test_same_file_but_different_url_is_downloaded_again(tmp_path: Path) -> None:
    """Regression: widening the weather window changes the URL; the old file is stale."""
    dest = tmp_path / "f"
    dest.write_bytes(b"old" * 100)
    known = ManifestEntry("s", "https://x/f?end=jan", "f", 300, sha256_file(dest), utc_now())
    c = client_for(lambda r: httpx.Response(200, content=BODY))
    res = download("https://x/f?end=may", dest, client=c, known=known)
    assert not res.skipped and dest.read_bytes() == BODY


def test_manifest_round_trip_and_upsert_does_not_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    m = Manifest(window={"start": "2024-01-01", "end": "2024-02-01"})
    e1 = ManifestEntry(
        "tlc_trips",
        "u",
        "raw/a.parquet",
        10,
        "h1",
        "2026-01-01T00:00:00+00:00",
        rows=5,
        columns={"a": "int64"},
    )
    m.upsert(e1)
    m.upsert(
        ManifestEntry("tlc_trips", "u", "raw/a.parquet", 11, "h2", "2026-01-02T00:00:00+00:00")
    )
    m.save(path)
    loaded = Manifest.load(path)
    assert len(loaded.entries) == 1  # same path: replaced, not duplicated
    assert loaded.get("raw/a.parquet") is not None
    assert loaded.get("raw/a.parquet").sha256 == "h2"  # type: ignore[union-attr]
    assert loaded.window == {"start": "2024-01-01", "end": "2024-02-01"}
    assert not list(tmp_path.glob("*.tmp"))


def test_missing_manifest_loads_empty(tmp_path: Path) -> None:
    assert Manifest.load(tmp_path / "nope.json").entries == {}
