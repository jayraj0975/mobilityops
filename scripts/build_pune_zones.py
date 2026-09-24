"""Build src/mobilityops/pune/data/pune_zones.json from OpenStreetMap, once.

Overpass is a shared public service: this makes ONE query, identifies itself, and the result is
committed so nothing queries OpenStreetMap at run time. Re-run it only to refresh the zones.

    python scripts/build_pune_zones.py --dry-run   # query and print the count, write nothing
    python scripts/build_pune_zones.py             # query and write the zone file
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from mobilityops.city import PUNE
from mobilityops.pune.zones import build_zone_document, select_seeds

OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "MobilityOps/0.2 (student portfolio project; github.com/jayraj0975/mobilityops)"
OUT = Path(__file__).resolve().parents[1] / "src/mobilityops/pune/data/pune_zones.json"


def fetch() -> list[dict]:  # type: ignore[type-arg]
    s, w, n, e = PUNE.bbox
    query = (
        f"[out:json][timeout:60];node[place~'^(suburb|neighbourhood|quarter)$']"
        f"({s},{w},{n},{e});out;"
    )
    resp = httpx.post(
        OVERPASS, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=90
    )
    resp.raise_for_status()
    return list(resp.json()["elements"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="query and report, write nothing")
    args = ap.parse_args()
    elements = fetch()
    seeds = select_seeds(elements, PUNE.bbox)
    print(f"{len(elements)} place nodes returned; {len(seeds)} usable zone seeds")
    if args.dry_run:
        return 0
    doc = build_zone_document(elements, PUNE.bbox, datetime.now(UTC).isoformat(timespec="seconds"))
    OUT.write_text(
        json.dumps(doc, separators=(",", ":"), ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(doc['zones'])} zones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
