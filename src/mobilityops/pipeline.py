"""The data pipeline: bronze checks -> silver -> checks -> gold -> checks -> promote.

Each stage's quality report is written to ``processed/<mode>/quality/`` and stored in the database.
A FAIL at any stage raises :class:`QualityGateError` and stops the run; the previously promoted
database (if any) is left exactly as it was.
"""

from __future__ import annotations

import platform
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import lightgbm
import pandas as pd

from mobilityops.config import Settings
from mobilityops.ingestion.pipeline import load_manifest
from mobilityops.log import get_logger
from mobilityops.quality.checks import (
    QualityGateError,
    QualityReport,
    check_bronze,
    check_gold,
    check_silver,
)
from mobilityops.transform.gold import (
    GoldResult,
    build_dim_zone,
    build_gold,
    building_path,
    promote,
)
from mobilityops.transform.silver import SilverResult, build_silver

log = get_logger("pipeline")


@dataclass(frozen=True)
class BuildResult:
    run_id: str
    db_path: Path
    silver: SilverResult
    gold: GoldResult
    reports: dict[str, QualityReport]


def quality_dir(settings: Settings) -> Path:
    return settings.processed_dir / "quality"


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _write_run_metadata(
    db_path: Path,
    settings: Settings,
    run_id: str,
    window: tuple[date, date],
    silver: SilverResult,
    reports: dict[str, QualityReport],
) -> None:
    run = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "mode": settings.mode,
                "built_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_commit": _git_commit(),
                "window_start": window[0].isoformat(),
                "window_end": window[1].isoformat(),
                "rows_in": silver.rows_in,
                "rows_valid": silver.rows_valid,
                "rows_rejected": silver.rows_rejected,
                "python": platform.python_version(),
                "duckdb": duckdb.__version__,
                "pandas": pd.__version__,
                "lightgbm": lightgbm.__version__,
                "synthetic": settings.mode == "sample",
            }
        ]
    )
    quality = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "stage": rep.stage,
                "check": res.name,
                "status": res.status.value,
                "message": res.message,
            }
            for rep in reports.values()
            for res in rep.results
        ]
    )
    con = duckdb.connect(str(db_path))
    try:
        con.register("run_df", run)
        con.execute("CREATE TABLE pipeline_run AS SELECT * FROM run_df")
        con.register("q_df", quality)
        con.execute("CREATE TABLE quality_result AS SELECT * FROM q_df")
    finally:
        con.close()


def build_all(settings: Settings) -> BuildResult:
    """Run the full pipeline. Raises QualityGateError on a FAIL, leaving any existing DB intact."""
    manifest = load_manifest(settings)
    if manifest.window is None:
        raise ValueError("manifest has no window; re-run ingestion")
    window = (
        date.fromisoformat(manifest.window["start"]),
        date.fromisoformat(manifest.window["end"]),
    )
    qdir = quality_dir(settings)
    reports: dict[str, QualityReport] = {}

    def gate(report: QualityReport) -> None:
        reports[report.stage] = report
        report.write(qdir / f"{report.stage}.json")
        log.info("quality", extra={"ctx": {"stage": report.stage, "overall": report.overall.value}})
        report.raise_if_failed()

    try:
        gate(check_bronze(manifest, settings.data_dir))

        zones = build_dim_zone(settings)
        zone_ids = {int(z) for z in zones.loc[zones["is_real_zone"], "location_id"]}
        silver = build_silver(settings, window, zone_ids)
        gate(check_silver(silver, window, zone_ids))

        gold = build_gold(settings, silver, window)
        gate(check_gold(gold.building_path, gold, silver, window))

        run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        _write_run_metadata(gold.building_path, settings, run_id, window, silver, reports)
        db_path = promote(settings)
    except QualityGateError:
        building_path(settings).unlink(missing_ok=True)  # never leave a half-built database
        raise
    log.info("pipeline complete", extra={"ctx": {"run_id": run_id, "db": str(db_path)}})
    return BuildResult(run_id, db_path, silver, gold, reports)
