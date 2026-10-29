import copy
import math

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics.pairwise import haversine_distances

from config.settings import EARTH_RADIUS_M, CandidateHotspotCriteria, DBSCANParams, KDEParams
from modules.contracts import (
    CLUSTER_LABEL_COLUMN,
    AnalysisError,
    ClusterResult,
    ClusterSummary,
    DensityResult,
)
from modules.data_validator import validate_and_clean
from modules.dbscan_analysis import run_dbscan
from modules.density_analysis import run_kde
from modules.spatial_statistics import compare_methods, haversine_m, summarize


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


# =====================================================================================
# Stage 6: summarize() and compare_methods()
# =====================================================================================

# Hand-built 3 x 4 (non-square) grid with binary-exact coordinates so that midpoint
# ties are exact. Rows follow latitude, columns follow longitude.
GRID_LAT = np.array([10.0, 10.5, 11.0])
GRID_LON = np.array([20.0, 20.25, 20.5, 20.75])
GRID_DENSITY = np.array(
    [
        [1.0, 5.0, 9.0, 0.0],   # lat 10.0
        [2.0, 6.0, 0.0, 0.0],   # lat 10.5
        [0.0, 0.0, 7.0, 3.0],   # lat 11.0
    ]
)
THRESHOLD = 5.0                 # high density: (0,1)=5 (equality), (0,2)=9, (1,1)=6, (2,2)=7
EXTENT = {"south": 10.0, "north": 11.0, "west": 20.0, "east": 20.75}

# (id, lat, lon, cluster label, expected node or None if outside, expected high)
CASES = [
    ("P0", 10.0, 20.25, 0, (0, 1), True),      # exact node, value == threshold
    ("P1", 10.125, 20.5, 0, (0, 2), True),     # between nodes, nearer row 0
    ("P2", 10.5, 20.3, 0, (1, 1), True),       # exact row, between columns
    ("P3", 11.0, 20.75, 1, (2, 3), False),     # north-east corner: boundary is inclusive
    ("P4", 10.75, 20.5, 1, (1, 2), False),     # latitude tie 10.5/11.0 -> lower row (value 0, not 7)
    ("P5", 10.0, 20.125, -1, (0, 0), False),   # longitude tie 20.0/20.25 -> lower column (1, not 5)
    ("P6", 10.5, 20.25, -1, (1, 1), True),     # noise at a high-density node
    ("P7", 9.99, 20.25, 0, None, False),       # south of grid -> outside, never snapped
    ("P8", 10.5, 20.76, -1, None, False),      # east of grid
    ("P9", 11.01, 20.0, 1, None, False),       # north of grid
    ("P10", 10.5, 19.99, -1, None, False),     # west of grid
]


def _clean(points, ids=None, index=None, extra=None):
    ids = ids or [f"I{i}" for i in range(len(points))]
    raw = pd.DataFrame(
        {"incident_id": ids, "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]},
        dtype=str,
    )
    for column, values in (extra or {}).items():
        raw[column] = values
    if index is not None:
        raw.index = index
    dataset = validate_and_clean(raw, "synthetic")
    assert dataset.report.rejected_rows == 0
    return dataset


def _cluster_result(dataset, labels, candidates=None):
    """A ClusterResult consistent with `labels`, built by hand (no DBSCAN)."""
    labeled = dataset.frame.copy()
    labeled[CLUSTER_LABEL_COLUMN] = np.asarray(labels, dtype="int64")
    lat = labeled["latitude"].to_numpy()
    lon = labeled["longitude"].to_numpy()
    summaries = []
    for label in sorted(set(labels) - {-1}):
        m = np.asarray(labels) == label
        summaries.append(
            ClusterSummary(
                cluster_label=label, incident_count=int(m.sum()),
                centroid_lat=float(lat[m].mean()), centroid_lon=float(lon[m].mean()), radius_m=0.0,
                is_candidate_hotspot=bool((candidates or {}).get(label, False)),
            )
        )
    return ClusterResult(labeled_frame=labeled, clusters=summaries, noise_count=int((np.asarray(labels) == -1).sum()),
                         params={})


def _density_result(n_points, grid_source="study_area", **overrides):
    fields = dict(
        grid_lat=GRID_LAT.copy(), grid_lon=GRID_LON.copy(), density=GRID_DENSITY.copy(),
        high_density_threshold=THRESHOLD,
        params={"n_points": n_points, "grid_extent": dict(EXTENT), "grid_source": grid_source},
    )
    fields.update(overrides)
    return DensityResult(**fields)


def _hand_built():
    dataset = _clean([(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
    clusters = _cluster_result(dataset, [c[3] for c in CASES], candidates={0: True})
    return dataset, clusters, _density_result(len(CASES))


# --- exact arithmetic ------------------------------------------------------------------


def test_two_by_two_table_and_totals_are_exact():
    _, clusters, density = _hand_built()
    mc = compare_methods(clusters, density)
    # clustered eligible: P0,P1,P2 (high) + P3,P4 (not); noise eligible: P6 (high) + P5 (not)
    assert (mc.clustered_high, mc.clustered_not_high, mc.noise_high, mc.noise_not_high) == (3, 2, 1, 1)
    assert (mc.clustered_eligible, mc.noise_eligible) == (5, 2)                     # row totals
    assert (mc.high_density_eligible, mc.not_high_density_eligible) == (4, 3)       # column totals
    assert mc.eligible_count == 7 and mc.outside_grid_count == 4 and mc.total_incidents == 11
    assert mc.clustered_high + mc.clustered_not_high == mc.clustered_eligible
    assert mc.noise_high + mc.noise_not_high == mc.noise_eligible
    assert mc.clustered_high + mc.noise_high == mc.high_density_eligible
    assert mc.clustered_not_high + mc.noise_not_high == mc.not_high_density_eligible
    assert mc.clustered_eligible + mc.noise_eligible == mc.eligible_count
    assert mc.eligible_count + mc.outside_grid_count == mc.total_incidents


def test_shares_use_eligible_denominators():
    _, clusters, density = _hand_built()
    mc = compare_methods(clusters, density)
    assert mc.clustered_high_share == 3 / 5
    assert mc.noise_high_share == 1 / 2


def test_per_cluster_counts_shares_and_candidate_flags():
    _, clusters, density = _hand_built()
    by_label = {c.cluster_label: c for c in compare_methods(clusters, density).per_cluster}
    a, b = by_label[0], by_label[1]
    # cluster 0: P0,P1,P2 eligible+high, P7 outside
    assert (a.incident_count, a.eligible_members, a.outside_grid_members, a.members_at_high_density) == (4, 3, 1, 3)
    assert a.high_density_share == 1.0 and a.is_candidate_hotspot is True
    # cluster 1: P3,P4 eligible not high, P9 outside
    assert (b.incident_count, b.eligible_members, b.outside_grid_members, b.members_at_high_density) == (3, 2, 1, 0)
    assert b.high_density_share == 0.0 and b.is_candidate_hotspot is False
    for c in by_label.values():
        assert c.eligible_members + c.outside_grid_members == c.incident_count
    assert sum(c.members_at_high_density for c in by_label.values()) == 3          # == clustered_high


def test_cluster_with_no_eligible_members_has_none_share():
    dataset = _clean([(10.0, 20.25), (10.5, 19.99)])          # second point is west of the grid
    clusters = _cluster_result(dataset, [-1, 0])
    mc = compare_methods(clusters, _density_result(2))
    (only,) = mc.per_cluster
    assert only.eligible_members == 0 and only.high_density_share is None
    assert mc.clustered_eligible == 0 and mc.clustered_high_share is None          # undefined, not 0
    assert mc.noise_high_share == 1.0


# --- grid lookup ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_each_point_is_classified_as_documented(case):
    """Each case alone: inside -> its expected node's class; outside -> excluded."""
    _, lat, lon, label, node, expected_high = case
    dataset = _clean([(lat, lon)])
    mc = compare_methods(_cluster_result(dataset, [0]), _density_result(1))   # one clustered point per case
    if node is None:
        assert mc.outside_grid_count == 1 and mc.eligible_count == 0
    else:
        assert mc.outside_grid_count == 0
        assert mc.clustered_high == int(expected_high)
        assert (GRID_DENSITY[node] >= THRESHOLD) == expected_high


def test_outside_points_are_not_snapped_even_next_to_a_high_node():
    # Just south of node (0,2) whose value 9 is high: snapping would wrongly count it as high.
    dataset = _clean([(9.9999, 20.5)])
    mc = compare_methods(_cluster_result(dataset, [0]), _density_result(1))
    assert mc.outside_grid_count == 1 and mc.clustered_high == 0 and mc.eligible_count == 0


def test_extent_inside_axes_limits_eligibility():
    # Axes extend to 11.0 but the documented extent stops at 10.6: a point at 10.8 is outside.
    density = _density_result(1)
    density.params["grid_extent"]["north"] = 10.6
    mc = compare_methods(_cluster_result(_clean([(10.8, 20.5)]), [0]), density)
    assert mc.outside_grid_count == 1


def test_orientation_rows_are_latitude():
    # (11.0, 20.5) is node [2, 2] = 7 (high); (10.5, 20.5) is node [1, 2] = 0 (not high).
    mc = compare_methods(_cluster_result(_clean([(11.0, 20.5)]), [0]), _density_result(1))
    assert mc.clustered_high == 1
    mc = compare_methods(_cluster_result(_clean([(10.5, 20.5)]), [0]), _density_result(1))
    assert mc.clustered_high == 0
    # (10.0, 20.5) reads [0, 2] = 9 (high); a transposed lookup would hit index [2, 0] = 0.
    mc = compare_methods(_cluster_result(_clean([(10.0, 20.5)]), [0]), _density_result(1))
    assert mc.clustered_high == 1


def test_comparison_uses_existing_threshold_without_refitting():
    _, clusters, density = _hand_built()
    density.high_density_threshold = 6.5                     # now only 9 and 7 are high
    mc = compare_methods(clusters, density)
    assert (mc.clustered_high, mc.noise_high) == (1, 0)      # only P1 (9); P0=5, P2=6, P6=6 drop out


# --- summarize: optional analyses ------------------------------------------------------------


def _real_inputs():
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(8)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500), (22.9500, 72.4500)]
    dataset = _clean(points, extra={"severity": ["major"] * 5 + ["minor"] * 9 + ["", " "]})
    clusters = run_dbscan(dataset, DBSCANParams(eps_m=250, min_samples=5), CandidateHotspotCriteria(min_incidents=7))
    density = run_kde(dataset, KDEParams(bandwidth_m=300, grid_cell_m=150))
    return dataset, clusters, density


def test_neither_analysis_supplied():
    dataset, _, _ = _real_inputs()
    s = summarize(dataset, None, None)
    assert (s.cluster_count, s.candidate_hotspot_count, s.noise_share, s.method_comparison) == (None, None, None, None)
    assert any("DBSCAN was not run" in n for n in s.notes) and any("KDE was not run" in n for n in s.notes)


def test_dbscan_only():
    dataset, clusters, _ = _real_inputs()
    s = summarize(dataset, clusters, None)
    assert (s.cluster_count, s.candidate_hotspot_count) == (2, 1)
    assert s.noise_share == 2 / 16 and s.method_comparison is None
    assert any("KDE was not run" in n for n in s.notes)


def test_kde_only():
    dataset, _, density = _real_inputs()
    s = summarize(dataset, None, density)
    assert (s.cluster_count, s.candidate_hotspot_count, s.noise_share, s.method_comparison) == (None, None, None, None)
    assert any("Method comparison not computed" in n for n in s.notes)


def test_both_analyses_with_real_dbscan_and_kde():
    dataset, clusters, density = _real_inputs()
    s = summarize(dataset, clusters, density)
    mc = s.method_comparison
    assert mc is not None and mc.total_incidents == s.incident_count == 16
    assert mc.outside_grid_count == 0                                   # data-extent grid covers all points
    assert mc.clustered_eligible == 14 and mc.noise_eligible == 2
    assert mc.clustered_high + mc.clustered_not_high + mc.noise_high + mc.noise_not_high == 16
    assert mc.clustered_high_share is not None and mc.clustered_high_share >= (mc.noise_high_share or 0.0)
    assert [c.is_candidate_hotspot for c in mc.per_cluster] == [c.is_candidate_hotspot for c in clusters.clusters]
    assert summarize(dataset, clusters, density).method_comparison == compare_methods(clusters, density)


def test_zero_values_are_zero_not_none_when_dbscan_ran():
    dataset = _clean([(10.0, 20.0), (10.0001, 20.0)])
    all_clustered = summarize(dataset, _cluster_result(dataset, [0, 0]), None)
    assert all_clustered.noise_share == 0.0 and all_clustered.noise_share is not None
    assert all_clustered.candidate_hotspot_count == 0
    all_noise = summarize(dataset, _cluster_result(dataset, [-1, -1]), None)
    assert all_noise.cluster_count == 0 and all_noise.candidate_hotspot_count == 0 and all_noise.noise_share == 1.0


# --- summarize: dataset-level values -----------------------------------------------------------


def test_bounding_box_order_and_mean_center():
    s = summarize(_clean([(10.0, 21.0), (12.0, 20.0), (11.0, 23.0)]), None, None)
    assert s.bounding_box == (10.0, 20.0, 12.0, 23.0)                 # (min_lat, min_lon, max_lat, max_lon)
    assert s.mean_center == pytest.approx((11.0, 64.0 / 3))           # (mean lat, mean lon)
    assert s.incident_count == 3


def test_category_counts_with_missing_values_last():
    dataset = _clean([(1.0, 2.0)] * 5,
                     extra={"severity": ["minor", "", "major", "minor", " "], "incident_type": ["b", "a", "b", "b", "a"]})
    counts = summarize(dataset, None, None).by_category
    assert counts == {"severity": {"major": 1, "minor": 2, "(missing)": 2}, "incident_type": {"a": 2, "b": 3}}
    assert list(counts["severity"]) == ["major", "minor", "(missing)"]


def test_no_category_columns_gives_empty_mapping():
    dataset = _clean([(1.0, 2.0)], extra={"location_name": ["X"], "incident_date": ["2024-01-01"]})
    assert summarize(dataset, None, None).by_category == {}


def test_non_consecutive_source_index_is_supported():
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(6)] + [(23.1, 72.65)]
    dataset = _clean(points, index=[90, 3, 41, 7, 1000, 12, 5])
    clusters = run_dbscan(dataset, DBSCANParams(eps_m=250, min_samples=3), CandidateHotspotCriteria(min_incidents=3))
    density = run_kde(dataset, KDEParams(bandwidth_m=300, grid_cell_m=150))
    s = summarize(dataset, clusters, density)
    assert s.cluster_count == 1 and s.noise_share == 1 / 7
    assert s.method_comparison.clustered_eligible == 6 and s.method_comparison.noise_eligible == 1


# --- validation ----------------------------------------------------------------------------------


def test_unusable_and_empty_datasets_raise():
    raw = pd.DataFrame({"incident_id": ["", "B"], "latitude": ["1", "x"], "longitude": ["2", "2"]}, dtype=str)
    with pytest.raises(AnalysisError, match="unusable"):
        summarize(validate_and_clean(raw, "s"), None, None)
    empty = validate_and_clean(pd.DataFrame(columns=["incident_id", "latitude", "longitude"], dtype=str), "s")
    with pytest.raises(AnalysisError, match="unusable"):
        summarize(empty, None, None)


def test_cluster_result_with_different_index_is_rejected():
    dataset, clusters, _ = _hand_built()
    clusters.labeled_frame.index = range(100, 100 + len(CASES))
    with pytest.raises(AnalysisError, match="row index"):
        summarize(dataset, clusters, None)


def test_cluster_result_with_different_ids_is_rejected():
    dataset, clusters, _ = _hand_built()
    clusters.labeled_frame.loc[clusters.labeled_frame.index[2], "incident_id"] = "OTHER"
    with pytest.raises(AnalysisError, match="incident IDs"):
        summarize(dataset, clusters, None)


def test_cluster_result_with_different_coordinates_is_rejected():
    dataset, clusters, _ = _hand_built()
    clusters.labeled_frame.loc[clusters.labeled_frame.index[0], "latitude"] = 10.001
    with pytest.raises(AnalysisError, match="latitude"):
        summarize(dataset, clusters, None)


def _shift_labels(c):
    c.labeled_frame[CLUSTER_LABEL_COLUMN] = c.labeled_frame[CLUSTER_LABEL_COLUMN] - 5


def _float_labels(c):
    c.labeled_frame[CLUSTER_LABEL_COLUMN] = c.labeled_frame[CLUSTER_LABEL_COLUMN].astype(float)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (_shift_labels, ">= -1"),
        (_float_labels, "integers"),
        (lambda c: setattr(c, "noise_count", c.noise_count + 1), "noise_count"),
        (lambda c: setattr(c.clusters[0], "incident_count", 99), "reports 99"),
        (lambda c: c.clusters.pop(), "summaries do not match"),
        (lambda c: c.clusters.append(copy.copy(c.clusters[0])), "duplicate"),
    ],
    ids=["label-below-noise", "float-labels", "noise-count", "summary-count", "missing-summary", "duplicate-summary"],
)
def test_inconsistent_cluster_result_is_rejected(mutate, match):
    dataset, clusters, density = _hand_built()
    mutate(clusters)
    with pytest.raises(AnalysisError, match=match):
        summarize(dataset, clusters, None)
    with pytest.raises(AnalysisError, match=match):
        compare_methods(clusters, density)


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"params": {"n_points": 10, "grid_extent": dict(EXTENT)}}, "n_points"),
        ({"params": {"n_points": len(CASES)}}, "grid_extent"),
        ({"density": GRID_DENSITY.T.copy()}, "shape"),
        ({"density": np.where(GRID_DENSITY == 9.0, np.nan, GRID_DENSITY)}, "finite"),
        ({"density": -GRID_DENSITY}, "non-negative"),
        ({"grid_lat": GRID_LAT[::-1].copy()}, "ascending"),
        ({"grid_lon": np.array([20.0, np.inf, 20.5, 20.75])}, "finite"),
        ({"grid_lat": np.zeros((3, 1))}, "invalid grid_lat"),
        ({"high_density_threshold": float("nan")}, "threshold"),
        ({"params": {"n_points": len(CASES), "grid_extent": {**EXTENT, "north": 12.0}}}, "not covered"),
        ({"params": {"n_points": len(CASES), "grid_extent": {**EXTENT, "south": 10.9, "north": 10.1}}}, "inverted"),
    ],
    ids=["n_points", "no-extent", "shape", "nan-density", "negative-density", "descending-axis",
         "inf-axis", "2d-axis", "nan-threshold", "extent-beyond-axes", "inverted-extent"],
)
def test_invalid_density_result_is_rejected(overrides, match):
    dataset, clusters, _ = _hand_built()
    density = _density_result(len(CASES), **overrides)
    with pytest.raises(AnalysisError, match=match):
        summarize(dataset, None, density)
    with pytest.raises(AnalysisError, match=match):
        compare_methods(clusters, density)


def test_data_extent_grid_with_points_outside_is_a_mismatch():
    _, clusters, _ = _hand_built()
    with pytest.raises(AnalysisError, match="data extent"):
        compare_methods(clusters, _density_result(len(CASES), grid_source="data_extent_padded"))


# --- robustness and wording ------------------------------------------------------------------------


def test_inputs_are_not_mutated():
    dataset, clusters, density = _hand_built()
    frame_before = dataset.frame.copy(deep=True)
    labeled_before = clusters.labeled_frame.copy(deep=True)
    summaries_before = copy.deepcopy(clusters.clusters)
    arrays_before = (density.grid_lat.copy(), density.grid_lon.copy(), density.density.copy())
    params_before = copy.deepcopy(density.params)
    summarize(dataset, clusters, density)
    compare_methods(clusters, density)
    pd.testing.assert_frame_equal(dataset.frame, frame_before)
    pd.testing.assert_frame_equal(clusters.labeled_frame, labeled_before)
    assert clusters.clusters == summaries_before and density.params == params_before
    for after, before in zip((density.grid_lat, density.grid_lon, density.density), arrays_before):
        assert np.array_equal(after, before)


def test_results_are_deterministic():
    dataset, clusters, density = _real_inputs()
    assert summarize(dataset, clusters, density) == summarize(dataset, clusters, density)


def test_notes_carry_caveats_and_never_claim_significance():
    dataset, clusters, density = _hand_built()
    s = summarize(dataset, clusters, density)
    text = " ".join(s.notes + s.method_comparison.notes)
    for phrase in ("descriptive", "relative density scores", "not incident counts or incidents per km2",
                   "nearest KDE grid node", "specific to this analysis and grid extent",
                   "excluded from the comparison denominators", "180-degree meridian"):
        assert phrase in text
    for note in s.notes + s.method_comparison.notes:
        if "significan" in note or "association" in note:
            assert "not" in note or "None of" in note
    assert any("4 incident(s) lie outside the KDE grid extent" in n for n in s.notes)
