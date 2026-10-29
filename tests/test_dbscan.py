import math

import pytest

from config.settings import EARTH_RADIUS_M, DBSCANParams
from modules.dbscan_analysis import metres_to_radians


def test_metres_to_radians_round_trip():
    assert math.isclose(metres_to_radians(250.0) * EARTH_RADIUS_M, 250.0)


def test_dbscan_params_reject_non_positive_eps():
    with pytest.raises(ValueError):
        DBSCANParams(eps_m=0)


@pytest.mark.skip(reason="Stage 4: run_dbscan not implemented")
def test_two_separated_groups_form_two_clusters():
    """Two synthetic groups ~5 km apart, eps 250 m -> exactly 2 clusters."""
    pytest.fail("Test implementation pending")
