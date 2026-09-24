"""`serve` must not let open event streams hold the process up at shutdown."""

from __future__ import annotations

from typing import Any

import pytest

from mobilityops import cli


def test_serve_bounds_graceful_shutdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """A server-sent event stream never ends by itself: without a bound, `docker stop` and
    `systemctl stop` wait for every connected viewer and then kill the process (found on a device,
    where the old server was still alive after SIGTERM)."""
    seen: dict[str, Any] = {}
    monkeypatch.setenv("MOBILITYOPS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MOBILITYOPS_MODE", "sample")
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: seen.update(kw))
    assert cli.main(["serve", "--port", "8123"]) == 0
    assert seen["timeout_graceful_shutdown"] == cli.GRACEFUL_SHUTDOWN_SECONDS
    assert (
        1 <= cli.GRACEFUL_SHUTDOWN_SECONDS <= 30
    )  # long enough for a request, short enough to stop
