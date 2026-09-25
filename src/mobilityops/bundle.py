"""Demo-bundle provenance and compatibility.

A *bundle* is the derived data and model artifacts that ``scripts/pack_demo.py`` packs for a hosted
demo. Code and bundle are released separately, so they can drift: the database may come from a
different pipeline run than the forecasts made from it, or from a schema the running code no longer
reads. This module makes that visible.

* ``build_manifest`` writes ``BUNDLE_MANIFEST.json`` into the archive: the code commit it was
  packed from, the pipeline run and commit that built the database, the model and the data run
  each artifact was made from, the schema fingerprint, and a SHA-256 for every file.
* ``check_bundle`` reads an extracted bundle and reports **problems** (the code cannot use it, or
  a file was altered) and **warnings** (it works but is inconsistent or unlabelled).
  ``mobilityops bundle-check`` runs it; CI runs it against the bundles the Render blueprint
  points at.
* ``summary`` is the cheap version the API serves in ``/api/v1/meta``.

The schema the code expects is ``CORE_SCHEMA``. A test builds the synthetic sample database and
asserts these tables and columns match it exactly, so changing the gold layer without updating this
file (and so the schema fingerprint) fails the suite instead of silently orphaning old bundles.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_NAME = "BUNDLE_MANIFEST.json"
MANIFEST_VERSION = 1
# Bump when CORE_SCHEMA changes in a way that makes older bundles unusable.
SCHEMA_VERSION = 1

# table -> ((column, DuckDB type), ...). The tables every mode builds; a bundle may hold more
# (dim_service and fact_service_zone_hourly in New York, sim_events in Pune).
CORE_SCHEMA: dict[str, tuple[tuple[str, str], ...]] = {
    "dim_date": (
        ("date", "TIMESTAMP_S"),
        ("day_of_week", "INTEGER"),
        ("day_name", "VARCHAR"),
        ("is_weekend", "BOOLEAN"),
        ("is_holiday", "BOOLEAN"),
        ("holiday_name", "VARCHAR"),
    ),
    "dim_hour": (
        ("hour_ts", "TIMESTAMP_S"),
        ("date", "TIMESTAMP_S"),
        ("hour_of_day", "INTEGER"),
        ("day_of_week", "INTEGER"),
        ("is_weekend", "BOOLEAN"),
        ("is_holiday", "BOOLEAN"),
        ("is_dst_gap", "BOOLEAN"),
        ("is_dst_overlap", "BOOLEAN"),
        ("is_valid", "BOOLEAN"),
        ("is_modelable", "BOOLEAN"),
    ),
    "dim_zone": (
        ("location_id", "BIGINT"),
        ("borough", "VARCHAR"),
        ("zone", "VARCHAR"),
        ("service_zone", "VARCHAR"),
        ("centroid_lon", "DOUBLE"),
        ("centroid_lat", "DOUBLE"),
        ("area_deg2", "DOUBLE"),
        ("is_real_zone", "BOOLEAN"),
    ),
    "dq_unallocated_dropoffs": (
        ("reason", "VARCHAR"),
        ("do_zone", "INTEGER"),
        ("trips", "BIGINT"),
    ),
    "fact_weather_daily": (
        ("date", "TIMESTAMP"),
        ("prcp_mm", "DOUBLE"),
        ("snow_mm", "DOUBLE"),
        ("tmax_c", "DOUBLE"),
        ("tmin_c", "DOUBLE"),
        ("is_rain", "BOOLEAN"),
        ("is_snow", "BOOLEAN"),
        ("is_freezing", "BOOLEAN"),
    ),
    "fact_zone_hourly_demand": (
        ("location_id", "BIGINT"),
        ("hour_ts", "TIMESTAMP_S"),
        ("pickups", "INTEGER"),
        ("dropoffs", "INTEGER"),
        ("revenue", "DOUBLE"),
        ("passengers", "DOUBLE"),
    ),
    "pipeline_run": (
        ("run_id", "VARCHAR"),
        ("mode", "VARCHAR"),
        ("built_at_utc", "VARCHAR"),
        ("git_commit", "VARCHAR"),
        ("window_start", "VARCHAR"),
        ("window_end", "VARCHAR"),
        ("rows_in", "BIGINT"),
        ("rows_valid", "BIGINT"),
        ("rows_rejected", "BIGINT"),
        ("python", "VARCHAR"),
        ("duckdb", "VARCHAR"),
        ("pandas", "VARCHAR"),
        ("lightgbm", "VARCHAR"),
        ("synthetic", "BOOLEAN"),
    ),
    "quality_result": (
        ("run_id", "VARCHAR"),
        ("stage", "VARCHAR"),
        ("check", "VARCHAR"),
        ("status", "VARCHAR"),
        ("message", "VARCHAR"),
    ),
}


def schema_sha256() -> str:
    """Fingerprint of the schema this code expects (and of ``SCHEMA_VERSION``)."""
    canon = json.dumps({"version": SCHEMA_VERSION, "tables": CORE_SCHEMA}, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": self.problems, "warnings": self.warnings, **self.info}


# ------------------------------------------------------------------------------- reading a bundle
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _db_path(root: Path, mode: str) -> Path:
    return root / "data" / "processed" / mode / "mobilityops.duckdb"


def _forecast_dir(root: Path, mode: str) -> Path:
    return root / "artifacts" / mode / "forecast"


def db_schema(db_path: Path) -> dict[str, list[tuple[str, str]]]:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
        ).fetchall()
    finally:
        con.close()
    out: dict[str, list[tuple[str, str]]] = {}
    for table, column, dtype in rows:
        out.setdefault(table, []).append((column, dtype))
    return out


def latest_run(db_path: Path) -> dict[str, Any] | None:
    """The newest ``pipeline_run`` row: which run and which code commit built the database."""
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT run_id, built_at_utc, git_commit, window_start, window_end, mode "
            "FROM pipeline_run ORDER BY built_at_utc DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    keys = ("run_id", "built_at_utc", "git_commit", "window_start", "window_end", "mode")
    return dict(zip(keys, row, strict=True))


def _json(path: Path) -> dict[str, Any] | None:
    return dict(json.loads(path.read_text())) if path.exists() else None


def artifact_runs(root: Path, mode: str) -> dict[str, Any]:
    """The model, and the data run each artifact says it was made from."""
    fdir = _forecast_dir(root, mode)
    latest = _json(fdir / "models" / "latest.json")
    model_id = str(latest["model_id"]) if latest else None
    meta = _json(fdir / "models" / model_id / "meta.json") if model_id else None
    evaluation = _json(fdir / "evaluation.json")
    anomaly = _json(root / "artifacts" / mode / "anomaly" / "report.json")
    return {
        "model_id": model_id,
        "model_meta": meta,
        "model_created_at_utc": (meta or {}).get("created_at_utc"),
        "model_data_run_id": (meta or {}).get("data_run_id"),
        "evaluation_data_run_id": (evaluation or {}).get("data_run_id"),
        "anomaly_data_run_id": (anomaly or {}).get("data_run_id"),
    }


def _git(*args: str, cwd: Path) -> str | None:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            ["git", *args],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------------------------- the manifest
def build_manifest(root: Path, mode: str, files: list[Path]) -> dict[str, Any]:
    """The manifest for the bundle made of ``files`` (paths under ``root``)."""
    from mobilityops import __version__

    run = latest_run(_db_path(root, mode)) or {}
    arts = artifact_runs(root, mode)
    listing = [
        {"path": str(f.relative_to(root)), "bytes": f.stat().st_size, "sha256": sha256_file(f)}
        for f in files
    ]
    report = check_files_consistency(run.get("run_id"), arts)
    return {
        "manifest_version": MANIFEST_VERSION,
        "kind": mode,
        "package_version": __version__,
        # The commit this bundle was packed and validated from. The database was built by
        # `data_built_by_commit`, which can be an earlier one: both are recorded.
        "code_commit": _git("rev-parse", "HEAD", cwd=root),
        "code_dirty": bool(_git("status", "--porcelain", "--", "src", cwd=root)),
        "schema_version": SCHEMA_VERSION,
        "schema_sha256": schema_sha256(),
        "data_run_id": run.get("run_id"),
        "data_built_at_utc": run.get("built_at_utc"),
        "data_built_by_commit": run.get("git_commit"),
        "data_window": {"start": run.get("window_start"), "end": run.get("window_end")},
        "model_id": arts["model_id"],
        "model_created_at_utc": arts["model_created_at_utc"],
        "model_data_run_id": arts["model_data_run_id"],
        "evaluation_data_run_id": arts["evaluation_data_run_id"],
        "anomaly_data_run_id": arts["anomaly_data_run_id"],
        "consistent": not report,
        "inconsistencies": report,
        "files": listing,
        "files_sha256": hashlib.sha256(json.dumps(listing, sort_keys=True).encode()).hexdigest(),
    }


def check_files_consistency(db_run_id: str | None, arts: dict[str, Any]) -> list[str]:
    """Each artifact should be made from the database's own pipeline run."""
    out = []
    for label, key in (
        ("the trained model", "model_data_run_id"),
        ("the evaluation", "evaluation_data_run_id"),
        ("the anomaly report", "anomaly_data_run_id"),
    ):
        got = arts.get(key)
        if got is not None and db_run_id is not None and got != db_run_id:
            out.append(f"{label} was made from data run {got}, but the database is run {db_run_id}")
    return out


# ---------------------------------------------------------------------------------- the checker
def check_bundle(root: Path, mode: str, *, verify_files: bool = True) -> Report:
    """Whether the bundle at ``root`` can be served by this code, and whether it is consistent."""
    rep = Report()
    db = _db_path(root, mode)
    if not db.exists():
        rep.problems.append(f"missing database {db.relative_to(root)}")
        return rep

    # 1. the database has every table and column this code reads, with the same types
    schema = db_schema(db)
    for table, cols in CORE_SCHEMA.items():
        have = dict(schema.get(table, []))
        if table not in schema:
            rep.problems.append(f"table {table} is missing")
            continue
        for col, dtype in cols:
            if col not in have:
                rep.problems.append(f"{table}.{col} is missing")
            elif have[col] != dtype:
                rep.problems.append(f"{table}.{col} is {have[col]}, this code expects {dtype}")

    run = latest_run(db)
    if run is None:
        rep.problems.append("the database has no pipeline_run record")
        return rep
    if run["mode"] != mode:
        rep.problems.append(f"the database was built in mode {run['mode']!r}, expected {mode!r}")
    rep.info.update(
        data_run_id=run["run_id"],
        data_built_by_commit=run["git_commit"],
        data_built_at_utc=run["built_at_utc"],
    )

    # 2. the trained model matches the features this code would compute for it
    arts = artifact_runs(root, mode)
    rep.info["model_id"] = arts["model_id"]
    if arts["model_id"] is None:
        rep.warnings.append("no trained model in the bundle")
    else:
        meta = arts["model_meta"]
        if meta is None:
            rep.problems.append(f"model {arts['model_id']} has no meta.json")
        else:
            from mobilityops.forecasting.features import feature_columns

            expected = feature_columns(
                oracle_weather="prcp_mm" in meta["features"],
                holiday_features="is_long_weekend" in meta["features"],
            )
            if list(meta["features"]) != expected:
                rep.problems.append(
                    "the model's features differ from what this code computes: "
                    f"{sorted(set(meta['features']) ^ set(expected))}"
                )
            if meta.get("mode") != mode:
                rep.problems.append(f"the model was trained in mode {meta.get('mode')!r}")

    # 3. artifacts made from one database, not several
    for msg in check_files_consistency(run["run_id"], arts):
        rep.warnings.append(msg + " (regenerate the artifacts, or repack after a rebuild)")

    # 4. the manifest, when there is one
    manifest = _json(root / MANIFEST_NAME)
    if manifest is None:
        rep.warnings.append(f"no {MANIFEST_NAME}: this bundle cannot say which commit produced it")
    else:
        rep.info["manifest"] = {
            k: manifest.get(k)
            for k in (
                "kind",
                "package_version",
                "code_commit",
                "data_run_id",
                "data_built_by_commit",
                "model_id",
                "schema_version",
                "files_sha256",
            )
        }
        if manifest.get("manifest_version") != MANIFEST_VERSION:
            rep.problems.append(f"unknown manifest version {manifest.get('manifest_version')!r}")
        if manifest.get("kind") != mode:
            rep.problems.append(f"the manifest is for {manifest.get('kind')!r}, not {mode!r}")
        if manifest.get("schema_sha256") != schema_sha256():
            rep.problems.append(
                f"the bundle was packed for schema {manifest.get('schema_version')} "
                f"({str(manifest.get('schema_sha256'))[:12]}...), this code expects "
                f"{SCHEMA_VERSION} ({schema_sha256()[:12]}...)"
            )
        if manifest.get("data_run_id") != run["run_id"]:
            rep.problems.append("the manifest's data run is not the database's data run")
        if verify_files:
            for entry in manifest.get("files", []):
                path = root / entry["path"]
                if not path.exists():
                    rep.problems.append(f"{entry['path']} is listed in the manifest but missing")
                elif sha256_file(path) != entry["sha256"]:
                    rep.problems.append(f"{entry['path']} does not match its manifest SHA-256")
    return rep


def summary(root: Path) -> dict[str, Any] | None:
    """What the API reports about its bundle: the manifest, without re-hashing any file."""
    manifest = _json(root / MANIFEST_NAME)
    if manifest is None:
        return None
    return {
        k: manifest.get(k)
        for k in (
            "kind",
            "package_version",
            "code_commit",
            "data_run_id",
            "data_built_by_commit",
            "data_built_at_utc",
            "model_id",
            "schema_version",
            "consistent",
            "inconsistencies",
            "files_sha256",
        )
    }
