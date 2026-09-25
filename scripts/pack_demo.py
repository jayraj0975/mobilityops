"""Pack the derived, aggregate-only files the hosted demo needs into one archive.

The archive holds the gold DuckDB (pickups per zone per hour, zone dimension, daily weather,
quality results) and the generated model artifacts. It does not contain trip-level rows, the raw
downloads or the silver layer. Extract it at the repository root (or /app in the image) and run
the API with MOBILITYOPS_MODE=real.

    python scripts/pack_demo.py [--out dist/mobilityops-demo-real.tar.gz]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def real_include() -> tuple[str, ...]:
    """The New York bundle: the database, the latest model only (older registered models stay
    behind), the evaluation and predictions, the anomaly report and the optimisation backtest."""
    latest = ROOT / "artifacts/real/forecast/models/latest.json"
    if not latest.exists():
        raise SystemExit(
            "missing artifacts/real/forecast/models/latest.json: run the real pipeline first"
        )
    model_id = json.loads(latest.read_text())["model_id"]
    return (
        "data/processed/real/mobilityops.duckdb",
        "data/processed/real/quality",
        "artifacts/real/forecast/evaluation.json",
        "artifacts/real/forecast/predictions.parquet",
        "artifacts/real/forecast/models/latest.json",
        f"artifacts/real/forecast/models/{model_id}",
        "artifacts/real/anomaly",
        "artifacts/real/optimization",
    )


def bundle_note() -> str:
    """The README inside the archive, naming the window the data actually covers."""
    window = ""
    manifest = ROOT / "data" / "manifests" / "real" / "manifest.json"
    if manifest.exists():
        w = json.loads(manifest.read_text()).get("window") or {}
        if w.get("start") and w.get("end"):
            window = f" for {w['start']} up to (not including) {w['end']}"
    return (
        "MobilityOps data bundle: derived aggregates of NYC TLC trip records"
        f"{window} and generated model artifacts. Which services it holds (yellow taxis, and green "
        "taxis and high-volume for-hire vehicles when they were ingested) is recorded in the "
        "database's dim_service table. No trip-level rows. See docs/DATA_SOURCES.md and NOTICE.\n"
    )


def pune_include() -> tuple[str, ...]:
    """The Pune bundle: the database, the latest model only, and the worker's rain cache."""
    latest = ROOT / "artifacts/pune/forecast/models/latest.json"
    if not latest.exists():
        raise SystemExit(
            "missing artifacts/pune/forecast/models/latest.json: run the Pune pipeline first"
        )
    model_id = json.loads(latest.read_text())["model_id"]
    return (
        "data/processed/pune/mobilityops.duckdb",
        "data/processed/pune/quality",
        "data/raw/pune/weather_hourly.parquet",
        "data/raw/pune/weather_provenance.json",
        "artifacts/pune/forecast/evaluation.json",
        "artifacts/pune/forecast/predictions.parquet",
        "artifacts/pune/forecast/models/latest.json",
        f"artifacts/pune/forecast/models/{model_id}",
        "artifacts/pune/anomaly",
    )


def pune_note() -> str:
    return (
        "MobilityOps Pune bundle: the analytical database (SIMULATED trip counts on real rain, the "
        "Maharashtra holiday calendar and OpenStreetMap zones), the registered forecast model and "
        "its evaluation, the anomaly report and the cached rain history with its provenance. "
        "Nothing here describes real Pune traffic. Weather data by Open-Meteo.com (CC BY 4.0); "
        "map data (c) "
        "OpenStreetMap contributors (ODbL). See docs/PUNE_DATA_SOURCES.md.\n"
    )


def files(mode: str = "real") -> list[Path]:
    out: list[Path] = []
    for rel in pune_include() if mode == "pune" else real_include():
        p = ROOT / rel
        if not p.exists():
            raise SystemExit(f"missing {rel}: run the real pipeline first")
        out += sorted(q for q in p.rglob("*") if q.is_file()) if p.is_dir() else [p]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=("real", "pune"), default="real")
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--allow-inconsistent",
        action="store_true",
        help="pack even if the artifacts were made from a different data run than the database",
    )
    args = ap.parse_args()
    out = ROOT / (args.out or f"dist/mobilityops-demo-{args.mode}.tar.gz")
    out.parent.mkdir(parents=True, exist_ok=True)
    listing = files(args.mode)
    from mobilityops.bundle import MANIFEST_NAME, build_manifest

    manifest = build_manifest(ROOT, args.mode, listing)
    if manifest["inconsistencies"] and not args.allow_inconsistent:
        for msg in manifest["inconsistencies"]:
            print(f"inconsistent: {msg}", file=sys.stderr)
        raise SystemExit(
            "refusing to pack a bundle whose artifacts and database come from different data runs; "
            "regenerate the artifacts (docs/EVALUATION.md) or pass --allow-inconsistent"
        )
    with tarfile.open(out, "w:gz", compresslevel=9) as tar:
        for f in listing:
            info = tar.gettarinfo(f, arcname=str(f.relative_to(ROOT)))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0  # deterministic archive
            with f.open("rb") as fh:
                tar.addfile(info, fh)
        note = (bundle_note() if args.mode == "real" else pune_note()).encode()
        ti = tarfile.TarInfo("DEMO_README.txt")
        ti.size = len(note)
        tar.addfile(ti, io.BytesIO(note))
        blob = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        mi = tarfile.TarInfo(MANIFEST_NAME)
        mi.size = len(blob)
        tar.addfile(mi, io.BytesIO(blob))
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (out.parent / (out.name + ".sha256")).write_text(f"{digest}  {out.name}\n")
    print(
        json.dumps(
            {
                "archive": str(
                    out.resolve().relative_to(ROOT) if out.resolve().is_relative_to(ROOT) else out
                ),
                "bytes": out.stat().st_size,
                "sha256": digest,
                "files": len(listing),
                "code_commit": manifest["code_commit"],
                "data_run_id": manifest["data_run_id"],
                "model_id": manifest["model_id"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
