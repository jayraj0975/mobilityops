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
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = (
    "data/processed/real/mobilityops.duckdb",
    "data/processed/real/quality",
    "artifacts/real/forecast",
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


def files() -> list[Path]:
    out: list[Path] = []
    for rel in INCLUDE:
        p = ROOT / rel
        if not p.exists():
            raise SystemExit(f"missing {rel}: run the real pipeline first")
        out += sorted(q for q in p.rglob("*") if q.is_file()) if p.is_dir() else [p]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="dist/mobilityops-demo-real.tar.gz")
    out = ROOT / ap.parse_args().out
    out.parent.mkdir(parents=True, exist_ok=True)
    listing = files()
    with tarfile.open(out, "w:gz", compresslevel=9) as tar:
        for f in listing:
            info = tar.gettarinfo(f, arcname=str(f.relative_to(ROOT)))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0  # deterministic archive
            with f.open("rb") as fh:
                tar.addfile(info, fh)
        note = bundle_note().encode()
        ti = tarfile.TarInfo("DEMO_README.txt")
        ti.size = len(note)
        tar.addfile(ti, io.BytesIO(note))
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
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
