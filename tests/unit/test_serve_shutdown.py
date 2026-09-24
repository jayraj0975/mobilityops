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


def test_with_worker_runs_the_worker_beside_the_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Render's free web service has no background workers, so the worker can run on a thread."""
    started: list[Any] = []
    monkeypatch.setenv("MOBILITYOPS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MOBILITYOPS_MODE", "pune")
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    monkeypatch.setattr("mobilityops.pune.worker.start_worker_thread", lambda s: started.append(s))
    # no database yet: refuses instead of starting a worker that cannot work
    assert cli.main(["serve", "--with-worker"]) == 1 and not started
    db = tmp_path / "processed" / "pune" / "mobilityops.duckdb"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"")
    monkeypatch.setenv("MOBILITYOPS_WITH_WORKER", "true")  # the environment form, as on Render
    assert cli.main(["serve"]) == 0 and len(started) == 1
    monkeypatch.setenv("MOBILITYOPS_MODE", "sample")
    assert cli.main(["serve", "--with-worker"]) == 2  # only meaningful in pune mode


def test_worker_thread_starts_and_stops_on_request(tmp_path: Any) -> None:
    import threading

    from mobilityops.config import Settings
    from mobilityops.pune.worker import start_worker_thread

    settings = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path), "MOBILITYOPS_MODE": "pune"}
    )
    settings.ensure_dirs()
    thread, stop = start_worker_thread(settings)
    assert isinstance(thread, threading.Thread) and thread.daemon and thread.name == "pune-worker"
    stop.set()
    thread.join(timeout=30)
    assert not thread.is_alive()
