import random

import pytest

from app.geo import Route, decode, encode, haversine, kalman_step


def test_haversine_known_distance():
    # Meskel Square -> Bole Medhanialem is about 3 km
    d = haversine(9.01024, 38.76125, 8.99846, 38.78624)
    assert 2900 < d < 3100


def test_polyline_roundtrip():
    pts = [(9.0, 38.76), (9.01, 38.77), (9.02, 38.765)]
    back = decode(encode(pts))
    for (a, b), (c, d) in zip(pts, back):
        assert a == pytest.approx(c, abs=1e-5) and b == pytest.approx(d, abs=1e-5)


def test_route_projection_and_point_at():
    r = Route([(9.000, 38.760), (9.054, 38.760)])
    assert 5900 < r.length_m < 6100
    p = r.project(9.027, 38.7603)  # halfway, ~33 m east of the line
    assert abs(p.along_m - r.length_m / 2) < 20
    assert 25 < p.offset_m < 40
    lat, lon = r.point_at(r.length_m / 2)
    assert lat == pytest.approx(9.027, abs=1e-4)
    assert lon == pytest.approx(38.760, abs=1e-6)
    assert r.simplified(10) == r.points  # short routes are kept as they are
    dense = Route([(9.0 + i * 0.0005, 38.76) for i in range(100)])
    assert len(dense.simplified(10)) == 10


def test_projection_prefers_forward_progress():
    # A route that goes north then comes back south next to itself.
    r = Route([(9.000, 38.760), (9.010, 38.760), (9.010, 38.7605), (9.000, 38.7605)])
    far_along = r.project(9.005, 38.76025, min_along=1500).along_m
    assert far_along > 1500  # chooses the return leg, not the first one


def test_kalman_reduces_noise():
    rng = random.Random(1)
    truth = (9.0, 38.76)
    lat = lon = var = None
    raw_err = smooth_err = 0.0
    for _ in range(60):
        nlat = truth[0] + rng.gauss(0, 25) / 111_000
        nlon = truth[1] + rng.gauss(0, 25) / 111_000
        lat, lon, var = kalman_step(lat, lon, var, 5.0, nlat, nlon, 25.0, 0.0)
        raw_err += haversine(nlat, nlon, *truth)
        smooth_err += haversine(lat, lon, *truth)
    assert smooth_err < raw_err * 0.8
