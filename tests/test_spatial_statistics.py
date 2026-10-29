import math

import numpy as np
import pytest
from sklearn.metrics.pairwise import haversine_distances

from config.settings import EARTH_RADIUS_M
from modules.spatial_statistics import haversine_m


def test_haversine_one_degree_latitude():
    # ~111.2 km per degree of latitude on the mean-radius sphere
    assert abs(haversine_m(0, 0, 1, 0) - 111_195) < 50


def test_haversine_zero_and_symmetry():
    assert haversine_m(23.02, 72.57, 23.02, 72.57) == 0.0
    forward = haversine_m(23.02, 72.57, 23.05, 72.61)
    assert forward > 0
    assert haversine_m(23.05, 72.61, 23.02, 72.57) == pytest.approx(forward, rel=1e-12)


def test_haversine_one_degree_longitude_shrinks_with_latitude():
    # Closed form for two points on the same parallel: d = 2R asin(cos(lat) sin(dlon/2)).
    at_equator = haversine_m(0, 0, 0, 1)
    at_60 = haversine_m(60, 0, 60, 1)
    assert at_equator == pytest.approx(EARTH_RADIUS_M * math.radians(1), rel=1e-12)
    expected_60 = 2 * EARTH_RADIUS_M * math.asin(math.cos(math.radians(60)) * math.sin(math.radians(0.5)))
    assert at_60 == pytest.approx(expected_60, rel=1e-12)
    assert at_60 < at_equator


@pytest.mark.parametrize(
    "p1,p2",
    [((23.0225, 72.5714), (23.0300, 72.5800)), ((-33.8688, 151.2093), (51.5074, -0.1278)), ((0, 179.9), (0, -179.9))],
)
def test_haversine_matches_independent_reference(p1, p2):
    expected = haversine_distances(np.radians([p1]), np.radians([p2]))[0, 0] * EARTH_RADIUS_M
    assert haversine_m(*p1, *p2) == pytest.approx(expected, rel=1e-9)


def test_haversine_antipodes_is_half_circumference():
    assert haversine_m(0, 0, 0, 180) == pytest.approx(math.pi * EARTH_RADIUS_M, rel=1e-12)
