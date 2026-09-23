"""The frontend contract: generated types must match the API, and the built UI is served safely."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from mobilityops.api.app import CSP, WEB_DIST_ENV, create_app

REPO = Path(__file__).resolve().parents[2]


def test_committed_openapi_matches_the_running_api(sample_settings) -> None:  # type: ignore[no-untyped-def]
    """If this fails the API changed: run `make web-types`."""
    committed = json.loads((REPO / "apps" / "web" / "openapi.json").read_text())
    current = json.loads(json.dumps(create_app(sample_settings).openapi(), sort_keys=True))
    assert current == committed


def test_built_ui_is_served_with_a_strict_content_security_policy(  # type: ignore[no-untyped-def]
    built_sample, tmp_path, monkeypatch
) -> None:
    sample_settings, _ = built_sample
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>MobilityOps</title><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log('x')")
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))
    client = TestClient(create_app(sample_settings))

    page = client.get("/")
    assert page.status_code == 200 and "MobilityOps" in page.text
    assert page.headers["Content-Security-Policy"] == CSP
    assert (
        "script-src 'self'" in CSP and "unsafe-eval" not in CSP and "frame-ancestors 'none'" in CSP
    )
    assert client.get("/assets/app.js").status_code == 200
    # API responses are not given the page policy, and keep working beside the mounted UI
    api = client.get("/api/v1/zones")
    assert api.status_code == 200 and "Content-Security-Policy" not in api.headers
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/no-such-file.txt").status_code == 404


def test_without_a_build_the_api_alone_still_works(sample_settings, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(WEB_DIST_ENV, str(tmp_path / "missing"))
    client = TestClient(create_app(sample_settings))
    assert client.get("/").status_code == 404
    assert client.get("/health").status_code == 200
