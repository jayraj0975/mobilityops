import math

import pytest

from mobilityops.geo import haversine_km, polygon_centroid

SQUARE = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
HOLE = [[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [1.5, 0.5], [0.5, 0.5]]  # opposite winding


def test_square_centroid_and_area() -> None:
    lon, lat, area = polygon_centroid([[SQUARE]])
    assert (lon, lat) == pytest.approx((1.0, 1.0))
    assert area == pytest.approx(4.0)


def test_hole_subtracts_area_but_symmetric_hole_keeps_centroid() -> None:
    lon, lat, area = polygon_centroid([[SQUARE, HOLE]])
    assert area == pytest.approx(4.0 - 1.0)
    assert (lon, lat) == pytest.approx((1.0, 1.0))


def test_multipolygon_is_area_weighted() -> None:
    small = [[10.0, 0.0], [11.0, 0.0], [11.0, 1.0], [10.0, 1.0], [10.0, 0.0]]  # area 1, centre 10.5
    lon, _, area = polygon_centroid([[SQUARE], [small]])
    assert area == pytest.approx(5.0)
    assert lon == pytest.approx((1.0 * 4 + 10.5 * 1) / 5)


def test_degenerate_ring_is_rejected() -> None:
    with pytest.raises(ValueError, match="zero area"):
        polygon_centroid([[[[0, 0], [1, 1], [2, 2], [0, 0]]]])


def test_haversine_known_distances() -> None:
    assert haversine_km(0, 0, 0, 0) == 0
    # one degree of latitude is about 111.2 km
    assert haversine_km(-74.0, 40.0, -74.0, 41.0) == pytest.approx(111.2, abs=0.2)
    # over a short distance haversine must agree with the independent equirectangular estimate
    lon1, lat1, lon2, lat2 = (
        -73.9855,
        40.758,
        -74.0445,
        40.6892,
    )  # Times Square -> Statue of Liberty
    km_per_deg = 111.195
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2)) * km_per_deg
    dy = (lat2 - lat1) * km_per_deg
    assert haversine_km(lon1, lat1, lon2, lat2) == pytest.approx(math.hypot(dx, dy), rel=0.005)
    assert math.isclose(haversine_km(-74, 40.7, -73.9, 40.8), haversine_km(-73.9, 40.8, -74, 40.7))
