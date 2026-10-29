"""DBSCAN tests. Synthetic, deterministic coordinates only."""

import math

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics.pairwise import haversine_distances

from config.settings import EARTH_RADIUS_M, AnalysisConfig, CandidateHotspotCriteria, DBSCANParams
from modules.app_controller import cluster_dataset
from modules.contracts import CLUSTER_LABEL_COLUMN, NOISE_LABEL, AnalysisError
from modules.data_validator import validate_and_clean
from modules.dbscan_analysis import MAX_EPS_M, metres_to_radians, run_dbscan

# ~0.0001 deg latitude ~= 11 m. Group A near (23.02, 72.57); group B ~5 km north.
GROUP_A = [(23.0200 + 0.0001 * i, 72.5700 + 0.0001 * (i % 2)) for i in range(6)]
GROUP_B = [(23.0650 + 0.0001 * i, 72.5700 + 0.0001 * (i % 3)) for i in range(12)]
NOISE = [(23.1000, 72.6500), (22.9500, 72.4500)]
CRITERIA = CandidateHotspotCriteria(min_incidents=10)


def _dataset(points, ids=None, index=None, extra=None):
    ids = ids or [f"P{i}" for i in range(len(points))]
    raw = pd.DataFrame(
        {"incident_id": ids, "latitude": [str(p[0]) for p in points], "longitude": [str(p[1]) for p in points]},
        dtype=str,
    )
    if extra:
        for col, values in extra.items():
            raw[col] = values
    if index is not None:
        raw.index = index
    dataset = validate_and_clean(raw, "synthetic")
    assert dataset.report.rejected_rows == 0
    return dataset


def _two_groups_with_noise():
    return _dataset(GROUP_A + GROUP_B + NOISE)


def _labels(result):
    return result.labeled_frame[CLUSTER_LABEL_COLUMN].tolist()


# --- core clustering -----------------------------------------------------------


def test_two_separated_groups_form_two_clusters():
    """Two synthetic groups ~5 km apart, eps 250 m -> exactly 2 clusters."""
    result = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=250, min_samples=5), CRITERIA)
    labels = _labels(result)
    assert len(result.clusters) == 2
    assert len(set(labels[:6])) == 1 and len(set(labels[6:18])) == 1
    assert labels[0] != labels[6] and NOISE_LABEL not in labels[:18]


def test_noise_points_are_labelled_minus_one_and_counted():
    result = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=250, min_samples=5), CRITERIA)
    assert _labels(result)[18:] == [NOISE_LABEL, NOISE_LABEL]
    assert result.noise_count == 2
    assert all(c.cluster_label != NOISE_LABEL for c in result.clusters)        # no summary for noise
    assert len(result.labeled_frame) == 20                                     # noise kept in output


def test_cluster_incident_counts():
    result = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=250, min_samples=5), CRITERIA)
    assert sorted(c.incident_count for c in result.clusters) == [6, 12]
    assert sum(c.incident_count for c in result.clusters) + result.noise_count == 20
    assert [c.cluster_label for c in result.clusters] == sorted(c.cluster_label for c in result.clusters)


def test_eps_is_applied_in_metres():
    """Two points ~222 m apart: one cluster at eps 250 m, both noise at eps 150 m."""
    dataset = _dataset([(23.0200, 72.5700), (23.0220, 72.5700)])
    assert len(run_dbscan(dataset, DBSCANParams(eps_m=250, min_samples=2), CRITERIA).clusters) == 1
    narrow = run_dbscan(dataset, DBSCANParams(eps_m=150, min_samples=2), CRITERIA)
    assert narrow.clusters == [] and narrow.noise_count == 2


def test_min_samples_counts_the_point_itself():
    result = run_dbscan(_dataset([(10.0, 20.0)]), DBSCANParams(eps_m=100, min_samples=1), CRITERIA)
    assert _labels(result) == [0] and result.clusters[0].incident_count == 1


def test_params_record_what_was_passed_to_sklearn():
    result = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=250, min_samples=5), CRITERIA)
    assert result.params == {
        "eps_m": 250.0, "eps_rad": 250 / EARTH_RADIUS_M, "min_samples": 5,
        "metric": "haversine", "algorithm": "ball_tree",
    }


# --- summaries -------------------------------------------------------------------


def test_centroid_is_arithmetic_mean_of_degrees():
    square = [(10.0000, 20.0000), (10.0010, 20.0000), (10.0000, 20.0010), (10.0010, 20.0010)]
    result = run_dbscan(_dataset(square), DBSCANParams(eps_m=200, min_samples=2), CRITERIA)
    (cluster,) = result.clusters
    assert cluster.centroid_lat == pytest.approx(10.0005, abs=1e-12)
    assert cluster.centroid_lon == pytest.approx(20.0005, abs=1e-12)


def test_radius_is_max_haversine_distance_in_metres():
    points = [(10.0000, 20.0000), (10.0010, 20.0000), (10.0000, 20.0010), (10.0020, 20.0020)]
    result = run_dbscan(_dataset(points), DBSCANParams(eps_m=500, min_samples=2), CRITERIA)
    (cluster,) = result.clusters
    assert cluster.incident_count == 4 and result.noise_count == 0                    # all four are members
    centre = np.radians([[cluster.centroid_lat, cluster.centroid_lon]])
    expected = (haversine_distances(centre, np.radians(points)) * EARTH_RADIUS_M).max()  # independent reference
    assert cluster.radius_m == pytest.approx(expected, rel=1e-9)
    assert 180 < cluster.radius_m < 200        # centroid (10.00075, 20.00075) -> far corner, ~0.00125 deg each way


def test_candidate_hotspot_threshold_is_inclusive():
    result = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=250, min_samples=5),
                        CandidateHotspotCriteria(min_incidents=12))
    flags = {c.incident_count: c.is_candidate_hotspot for c in result.clusters}
    assert flags == {6: False, 12: True}                                       # 12 >= 12 qualifies
    higher = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=250, min_samples=5),
                        CandidateHotspotCriteria(min_incidents=13))
    assert not any(c.is_candidate_hotspot for c in higher.clusters)


def test_min_density_per_km2_is_ignored():
    with_density = CandidateHotspotCriteria(min_incidents=6, min_density_per_km2=1e9)
    result = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=250, min_samples=5), with_density)
    assert all(c.is_candidate_hotspot for c in result.clusters)


# --- parameter validation ---------------------------------------------------------


@pytest.mark.parametrize("eps", [float("nan"), float("inf"), 3e7, True])
def test_invalid_eps_raises_analysis_error(eps):
    with pytest.raises(AnalysisError, match="eps_m"):
        run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=eps), CRITERIA)


def test_max_eps_is_exactly_half_the_circumference():
    assert MAX_EPS_M == math.pi * 6_371_008.8


def test_eps_equal_to_half_circumference_is_accepted():
    """At the boundary every pair of points is within eps, so all points form one cluster."""
    result = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=MAX_EPS_M, min_samples=2), CRITERIA)
    assert len(result.clusters) == 1 and result.noise_count == 0
    assert result.params["eps_m"] == MAX_EPS_M


def test_eps_just_above_half_circumference_is_rejected_with_clear_message():
    just_above = math.nextafter(MAX_EPS_M, math.inf)                           # smallest float > boundary
    with pytest.raises(AnalysisError) as excinfo:
        run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=just_above), CRITERIA)
    message = str(excinfo.value)
    assert "half the Earth's circumference" in message
    assert repr(MAX_EPS_M) in message and repr(just_above) in message


@pytest.mark.parametrize("eps", [0, -5])
def test_non_positive_eps_rejected_at_construction(eps):
    with pytest.raises(ValueError):
        DBSCANParams(eps_m=eps)


@pytest.mark.parametrize("min_samples", [2.5, True, np.float64(3.0)])
def test_invalid_min_samples_raises_analysis_error(min_samples):
    with pytest.raises(AnalysisError, match="min_samples"):
        run_dbscan(_two_groups_with_noise(), DBSCANParams(min_samples=min_samples), CRITERIA)


def test_zero_min_samples_rejected_at_construction():
    with pytest.raises(ValueError):
        DBSCANParams(min_samples=0)


@pytest.mark.parametrize("min_incidents", [0, -1, 2.5, True])
def test_invalid_min_incidents_raises_analysis_error(min_incidents):
    with pytest.raises(AnalysisError, match="min_incidents"):
        run_dbscan(_two_groups_with_noise(), DBSCANParams(), CandidateHotspotCriteria(min_incidents=min_incidents))


def test_numpy_integer_min_samples_is_accepted():
    result = run_dbscan(_two_groups_with_noise(), DBSCANParams(eps_m=250, min_samples=np.int64(5)), CRITERIA)
    assert result.params["min_samples"] == 5 and isinstance(result.params["min_samples"], int)


# --- input contracts ----------------------------------------------------------------


def test_unusable_dataset_raises_analysis_error():
    raw = pd.DataFrame({"incident_id": ["", "B"], "latitude": ["1", "x"], "longitude": ["2", "2"]}, dtype=str)
    unusable = validate_and_clean(raw, "synthetic")
    assert unusable.report.is_usable is False
    with pytest.raises(AnalysisError, match="unusable"):
        run_dbscan(unusable, DBSCANParams(), CRITERIA)
    with pytest.raises(AnalysisError, match="unusable"):
        cluster_dataset(unusable, AnalysisConfig())


def test_empty_dataset_raises_analysis_error():
    empty = validate_and_clean(pd.DataFrame(columns=["incident_id", "latitude", "longitude"], dtype=str), "s")
    with pytest.raises(AnalysisError):
        run_dbscan(empty, DBSCANParams(), CRITERIA)


def test_fewer_points_than_min_samples_is_all_noise_not_an_error():
    result = run_dbscan(_dataset([(10.0, 20.0), (10.0001, 20.0)]), DBSCANParams(eps_m=250, min_samples=5), CRITERIA)
    assert result.clusters == [] and result.noise_count == 2
    assert _labels(result) == [NOISE_LABEL, NOISE_LABEL]


def test_invalid_coordinates_in_a_hand_built_dataset_are_not_accepted():
    dataset = _dataset([(10.0, 20.0), (10.0001, 20.0)])
    dataset.frame.loc[dataset.frame.index[1], "latitude"] = np.nan
    with pytest.raises(AnalysisError, match="non-finite"):
        run_dbscan(dataset, DBSCANParams(), CRITERIA)


def test_existing_cluster_label_column_is_not_overwritten():
    dataset = _dataset([(10.0, 20.0)], extra={CLUSTER_LABEL_COLUMN: ["from-source"]})
    with pytest.raises(AnalysisError, match=CLUSTER_LABEL_COLUMN):
        run_dbscan(dataset, DBSCANParams(min_samples=1), CRITERIA)


# --- source-row identity ------------------------------------------------------------


def test_non_consecutive_source_index_is_preserved_and_labels_attached_by_position():
    points = GROUP_A[:3] + NOISE[:1] + GROUP_B[:3]
    index = [57, 3, 1000, 12, 8, 41, 2]
    result = run_dbscan(_dataset(points, index=index), DBSCANParams(eps_m=250, min_samples=3), CRITERIA)
    frame = result.labeled_frame
    assert list(frame.index) == index                                          # labels kept, not reset/sorted
    labels = _labels(result)
    assert labels[3] == NOISE_LABEL                                            # position 3 is the noise point
    assert len(set(labels[:3])) == 1 and len(set(labels[4:])) == 1 and labels[0] != labels[4]
    assert frame.loc[12, CLUSTER_LABEL_COLUMN] == NOISE_LABEL                  # traceable by source label
    assert frame.loc[12, "incident_id"] == "P3"


def test_incident_ids_and_row_order_are_preserved():
    ids = [f"Z{i:02d}" for i in range(19, -1, -1)]                            # deliberately not sorted
    result = run_dbscan(_dataset(GROUP_A + GROUP_B + NOISE, ids=ids), DBSCANParams(eps_m=250, min_samples=5), CRITERIA)
    assert result.labeled_frame["incident_id"].tolist() == ids
    # Stage 2's pd.to_numeric may differ from float() by 1 ulp (~1e-15 deg), hence the tolerance.
    np.testing.assert_allclose(
        result.labeled_frame[["latitude", "longitude"]].to_numpy(), np.array(GROUP_A + GROUP_B + NOISE), rtol=0, atol=1e-12
    )


def test_input_dataset_is_not_mutated():
    dataset = _dataset(GROUP_A + NOISE, index=[9, 7, 5, 3, 1, 0, 2, 4])
    before = dataset.frame.copy(deep=True)
    result = run_dbscan(dataset, DBSCANParams(eps_m=250, min_samples=3), CRITERIA)
    pd.testing.assert_frame_equal(dataset.frame, before)
    assert CLUSTER_LABEL_COLUMN not in dataset.frame.columns
    assert result.labeled_frame is not dataset.frame


def test_clustering_is_deterministic_for_fixed_input():
    dataset = _two_groups_with_noise()
    first = run_dbscan(dataset, DBSCANParams(eps_m=250, min_samples=5), CRITERIA)
    second = run_dbscan(dataset, DBSCANParams(eps_m=250, min_samples=5), CRITERIA)
    assert _labels(first) == _labels(second) and first.clusters == second.clusters


def test_controller_runs_dbscan_with_config():
    config = AnalysisConfig(dbscan=DBSCANParams(eps_m=250, min_samples=5), hotspot=CandidateHotspotCriteria(10))
    result = cluster_dataset(_two_groups_with_noise(), config)
    assert len(result.clusters) == 2 and result.noise_count == 2


# --- unit conversion ------------------------------------------------------------------


def test_metres_to_radians_round_trip():
    assert math.isclose(metres_to_radians(250.0) * EARTH_RADIUS_M, 250.0)


def test_metres_to_radians_matches_one_degree_of_arc():
    one_degree_m = EARTH_RADIUS_M * math.pi / 180
    assert math.isclose(metres_to_radians(one_degree_m), math.radians(1.0))
    assert metres_to_radians(250.0) == 250.0 / 6_371_008.8


def test_dbscan_params_reject_non_positive_eps():
    with pytest.raises(ValueError):
        DBSCANParams(eps_m=0)
