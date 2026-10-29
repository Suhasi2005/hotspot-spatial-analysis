import pytest


@pytest.mark.skip(reason="Stage 4: haversine_m not implemented")
def test_haversine_one_degree_latitude():
    from modules.spatial_statistics import haversine_m

    # ~111.2 km per degree of latitude on the mean-radius sphere
    assert abs(haversine_m(0, 0, 1, 0) - 111_195) < 50
