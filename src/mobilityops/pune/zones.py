"""Pune analysis zones: the service area of each OpenStreetMap suburb.

Pune publishes no ward polygons in OpenStreetMap, so zones are an analytical tessellation: every
point of the study area belongs to the nearest suburb seed (a Voronoi cell), clipped to the study
box. They are NOT administrative boundaries and are never described as such.

Cells are built by clipping the study box with the perpendicular bisector against every other seed.
That is exact, needs no geometry library, and always yields convex polygons.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib import resources
from typing import Any

BBox = tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)
Point = tuple[float, float]  # (x, y) in a local metric plane
PLACE_RANK = {"suburb": 0, "neighbourhood": 1, "quarter": 2}
MIN_SEED_SEPARATION_M = 700.0
EARTH_RADIUS_M = 6_371_000.0
ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0)"


@dataclass(frozen=True)
class Seed:
    name: str
    lat: float
    lon: float
    place: str  # suburb | neighbourhood | quarter
    osm_id: int


class Projection:
    """Equirectangular projection around a reference latitude (metres; close enough at 20 km)."""

    def __init__(self, lat0: float) -> None:
        self.lat0 = lat0
        self._kx = math.cos(math.radians(lat0)) * math.pi / 180.0 * EARTH_RADIUS_M
        self._ky = math.pi / 180.0 * EARTH_RADIUS_M

    def forward(self, lat: float, lon: float) -> Point:
        return (lon * self._kx, lat * self._ky)

    def inverse(self, p: Point) -> tuple[float, float]:
        return (p[1] / self._ky, p[0] / self._kx)  # (lat, lon)


def _clip(poly: list[Point], a: float, b: float, c: float) -> list[Point]:
    """Keep the part of a convex polygon where ``a*x + b*y <= c`` (Sutherland-Hodgman)."""
    out: list[Point] = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        fp = a * p[0] + b * p[1] - c
        fq = a * q[0] + b * q[1] - c
        if fp <= 0:
            out.append(p)
        if (fp < 0 < fq) or (fq < 0 < fp):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def polygon_area(poly: list[Point]) -> float:
    s = 0.0
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        s += p[0] * q[1] - q[0] * p[1]
    return abs(s) / 2.0


def voronoi_cells(points: list[Point], box: tuple[Point, Point]) -> list[list[Point]]:
    """One convex cell per point, clipped to the box ``((xmin, ymin), (xmax, ymax))``."""
    (x0, y0), (x1, y1) = box
    cells = []
    for i, p in enumerate(points):
        cell = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for j, q in enumerate(points):
            if i == j:
                continue
            # nearer to p than to q:  (q-p).x <= (|q|^2 - |p|^2) / 2
            a, b = q[0] - p[0], q[1] - p[1]
            c = (q[0] ** 2 + q[1] ** 2 - p[0] ** 2 - p[1] ** 2) / 2.0
            cell = _clip(cell, a, b, c)
            if not cell:
                break
        cells.append(cell)
    return cells


def select_seeds(elements: list[dict[str, Any]], bbox: BBox) -> list[Seed]:
    """Named suburbs/neighbourhoods/quarters inside the box, one per neighbourhood.

    Needs an English (or plain ASCII) name so the interface is readable; seeds closer than
    ``MIN_SEED_SEPARATION_M`` to a better-ranked one are dropped (they would make slivers).
    """
    lat_lo, lon_lo, lat_hi, lon_hi = bbox
    proj = Projection((lat_lo + lat_hi) / 2)
    candidates: list[Seed] = []
    for el in elements:
        tags = el.get("tags", {})
        place = tags.get("place")
        if el.get("type") != "node" or place not in PLACE_RANK:
            continue
        name = tags.get("name:en") or tags.get("name") or ""
        if not name or not name.isascii():
            continue
        lat, lon = float(el["lat"]), float(el["lon"])
        if not (lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi):
            continue
        candidates.append(Seed(name.strip(), lat, lon, place, int(el["id"])))
    candidates.sort(key=lambda s: (PLACE_RANK[s.place], s.name.lower(), s.osm_id))
    chosen: list[Seed] = []
    names: set[str] = set()
    for c in candidates:
        cp = proj.forward(c.lat, c.lon)
        if c.name.lower() in names:
            continue
        if any(math.dist(cp, proj.forward(s.lat, s.lon)) < MIN_SEED_SEPARATION_M for s in chosen):
            continue
        chosen.append(c)
        names.add(c.name.lower())
    chosen.sort(key=lambda s: (s.lat, s.lon))  # stable ids regardless of Overpass ordering
    return chosen


def build_zone_document(
    elements: list[dict[str, Any]], bbox: BBox, fetched_at: str
) -> dict[str, Any]:
    """The committed zone file: seeds, cells (lon/lat rings) and provenance."""
    seeds = select_seeds(elements, bbox)
    lat_lo, lon_lo, lat_hi, lon_hi = bbox
    proj = Projection((lat_lo + lat_hi) / 2)
    pts = [proj.forward(s.lat, s.lon) for s in seeds]
    lo, hi = proj.forward(lat_lo, lon_lo), proj.forward(lat_hi, lon_hi)
    cells = voronoi_cells(pts, (lo, hi))
    zones = []
    for zid, (seed, cell) in enumerate(zip(seeds, cells, strict=True), start=1):
        ring = [proj.inverse(p) for p in cell]
        zones.append(
            {
                "id": zid,
                "name": seed.name,
                "place": seed.place,
                "osm_id": seed.osm_id,
                "lat": round(seed.lat, 6),
                "lon": round(seed.lon, 6),
                "area_km2": round(polygon_area(cell) / 1e6, 3),
                "ring": [[round(lon, 5), round(lat, 5)] for lat, lon in ring],
            }
        )
    return {
        "city": "pune",
        "bbox": list(bbox),
        "attribution": ATTRIBUTION,
        "licence": "ODbL 1.0: https://opendatacommons.org/licenses/odbl/1-0/",
        "source": "OpenStreetMap place nodes via the Overpass API",
        "fetched_at": fetched_at,
        "method": (
            "each zone is the region closer to its suburb seed than to any other, clipped to "
            "the study box; an analytical tessellation, not an administrative boundary"
        ),
        "zones": zones,
    }


def load_zones() -> dict[str, Any]:
    """The committed zone document."""
    text = resources.files("mobilityops.pune").joinpath("data/pune_zones.json").read_text("utf-8")
    doc: dict[str, Any] = json.loads(text)
    return doc
