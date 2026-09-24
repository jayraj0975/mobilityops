"""Zone construction: exact tessellation, provenance, and the committed file."""

from __future__ import annotations

import math

from mobilityops.city import PUNE
from mobilityops.pune.zones import (
    Projection,
    load_zones,
    polygon_area,
    select_seeds,
    voronoi_cells,
)

BOX = ((0.0, 0.0), (10.0, 10.0))


def _node(i: int, name: str, lat: float, lon: float, place: str = "suburb") -> dict:  # type: ignore[type-arg]
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {"place": place, "name": name}}


def test_two_points_split_the_box_down_the_middle() -> None:
    cells = voronoi_cells([(2.0, 5.0), (8.0, 5.0)], BOX)
    assert math.isclose(polygon_area(cells[0]), 50.0) and math.isclose(polygon_area(cells[1]), 50.0)
    assert all(x <= 5.0 + 1e-9 for x, _ in cells[0])


def test_cells_tile_the_box_without_overlap() -> None:
    pts = [(1.0, 1.0), (9.0, 2.0), (5.0, 5.0), (2.0, 8.0), (8.0, 8.0), (4.0, 2.0)]
    cells = voronoi_cells(pts, BOX)
    assert math.isclose(sum(polygon_area(c) for c in cells), 100.0, rel_tol=1e-9)


def test_a_single_point_owns_the_whole_box() -> None:
    (cell,) = voronoi_cells([(3.0, 3.0)], BOX)
    assert math.isclose(polygon_area(cell), 100.0)


def test_seed_selection_filters_and_dedupes() -> None:
    lat0, lon0 = 18.5, 73.85
    els = [
        _node(1, "Kothrud", lat0, lon0),
        _node(2, "Kothrud Colony", lat0 + 0.001, lon0 + 0.001, "neighbourhood"),  # ~150 m away
        _node(3, "Baner", lat0 + 0.05, lon0),
        _node(4, "Outside", 30.0, 73.85),
        _node(5, "कोथरूड", lat0 - 0.05, lon0),  # not ASCII and no English name
        _node(6, "Baner", lat0 + 0.09, lon0),  # duplicate name
        {"type": "way", "id": 7, "tags": {"place": "suburb", "name": "Way"}},
    ]
    seeds = select_seeds(els, PUNE.bbox)
    assert [s.name for s in seeds] == ["Kothrud", "Baner"]


def test_english_name_is_preferred_over_the_local_one() -> None:
    el = _node(1, "कोथरूड", 18.5, 73.85)
    el["tags"]["name:en"] = "Kothrud"
    assert select_seeds([el], PUNE.bbox)[0].name == "Kothrud"


def test_projection_round_trips() -> None:
    proj = Projection(18.5)
    lat, lon = proj.inverse(proj.forward(18.52, 73.86))
    assert math.isclose(lat, 18.52) and math.isclose(lon, 73.86)


def test_committed_zone_file_is_consistent_and_attributed() -> None:
    doc = load_zones()
    zones = doc["zones"]
    assert "OpenStreetMap" in doc["attribution"] and "ODbL" in doc["licence"]
    assert len(zones) >= 50
    assert [z["id"] for z in zones] == list(range(1, len(zones) + 1))
    assert len({z["name"].lower() for z in zones}) == len(zones)
    s, w, n, e = doc["bbox"]
    proj = Projection((s + n) / 2)
    box_km2 = (n - s) * proj._ky * (e - w) * proj._kx / 1e6
    assert math.isclose(sum(z["area_km2"] for z in zones), box_km2, rel_tol=0.005)
    for z in zones:
        assert s <= z["lat"] <= n and w <= z["lon"] <= e
        assert len(z["ring"]) >= 3
