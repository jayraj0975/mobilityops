"""Small geometry helpers on longitude/latitude polygons (no GIS dependency needed).

Taxi zones are compact, so planar centroids in degrees are accurate enough for choosing a
representative point; distances between points use the haversine formula.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

Ring = Sequence[Sequence[float]]


def _ring_area_centroid(ring: Ring) -> tuple[float, float, float]:
    """Signed area and centroid of one closed ring (shoelace formula)."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in pairwise(ring):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if a == 0:
        raise ValueError("degenerate ring with zero area")
    return a, cx / (6 * a), cy / (6 * a)


def polygon_centroid(polygons: Sequence[Sequence[Ring]]) -> tuple[float, float, float]:
    """Centroid (lon, lat) and absolute area of a MultiPolygon.

    ``polygons`` is a list of polygons, each a list of rings (outer ring first, then holes).
    Holes subtract area, so a zone with an interior cut-out is weighted correctly.
    """
    total = wx = wy = 0.0
    for poly in polygons:
        for i, ring in enumerate(poly):
            a, cx, cy = _ring_area_centroid(ring)
            w = abs(a) * (1 if i == 0 else -1)
            total += w
            wx += cx * w
            wy += cy * w
    if total <= 0:
        raise ValueError("polygon has no positive area")
    return wx / total, wy / total, total


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
