"""KDE tests. Synthetic, deterministic data only; no network or tiles."""

import math

import numpy as np
import pandas as pd
import pytest
from sklearn.neighbors import KernelDensity

from config.settings import EARTH_RADIUS_M, AnalysisConfig, KDEParams, StudyArea
from modules.app_controller import estimate_density
from modules.contracts import AnalysisError
from modules.data_validator import validate_and_clean
from modules.density_analysis import MAX_GRID_CELLS, run_kde

CENTRE_A = (23.0200, 72.5700)
CENTRE_B = (23.0650, 72.5700)          # ~5 km north of A
FAST = KDEParams(bandwidth_m=300, grid_cell_m=100)


def _blob(centre, n, spread_deg=0.0004):
    """Deterministic ring-and-centre layout around `centre` (~40 m radius)."""
    pts = [centre]
    for k in range(n - 1):
        angle = 2 * math.pi * k / (n - 1)
        pts.append((centre[0] + spread_deg * math.sin(angle), centre[1] + spread_deg * math.cos(angle)))
    return pts


def _dataset(points, index=None):
    raw = pd.DataFrame(
        {"incident_id": [f"P{i}" for i in range(len(points))],
         "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]},
        dtype=str,
    )
    if index is not None:
        raw.index = index
    dataset = validate_and_clean(raw, "synthetic")
    assert dataset.report.rejected_rows == 0
    return dataset


def _peak(result):
    i, j = np.unravel_index(np.argmax(result.density), result.density.shape)
    return result.grid_lat[i], result.grid_lon[j]


def _value_at(result, lat, lon):
    i = int(np.argmin(np.abs(result.grid_lat - lat)))
    j = int(np.argmin(np.abs(result.grid_lon - lon)))
    return result.density[i, j]


# --- concentrations -----------------------------------------------------------------


def test_density_peaks_near_synthetic_concentration():
    """Density argmax should fall within one grid cell of a dense synthetic group."""
    result = run_kde(_dataset(_blob(CENTRE_A, 30)), FAST)
    peak_lat, peak_lon = _peak(result)
    assert abs(peak_lat - CENTRE_A[0]) <= result.params["lat_step_deg"]
    assert abs(peak_lon - CENTRE_A[1]) <= result.params["lon_step_deg"]


def test_concentrated_group_is_far_denser_than_background():
    result = run_kde(_dataset(_blob(CENTRE_A, 30)), FAST)
    corner = result.density[0, 0]   # ~3*sqrt(2) = 4.2 bandwidths from the group: Gaussian ratio ~1e4
    assert result.density.max() > 5_000 * corner
    assert (result.density >= 0).all()


def test_two_separated_concentrations_give_two_peaks():
    result = run_kde(_dataset(_blob(CENTRE_A, 20) + _blob(CENTRE_B, 20)), FAST)
    at_a = _value_at(result, *CENTRE_A)
    at_b = _value_at(result, *CENTRE_B)
    midpoint = _value_at(result, (CENTRE_A[0] + CENTRE_B[0]) / 2, CENTRE_A[1])
    assert at_a == pytest.approx(at_b, rel=0.05)                 # equal groups -> equal peaks
    assert min(at_a, at_b) > 1e6 * max(midpoint, 1e-300)         # deep trough between them
    upper = result.grid_lat > (CENTRE_A[0] + CENTRE_B[0]) / 2
    peak_b = np.unravel_index(np.argmax(result.density[upper]), result.density[upper].shape)
    assert abs(result.grid_lat[upper][peak_b[0]] - CENTRE_B[0]) <= result.params["lat_step_deg"]


# --- grid, shape, orientation ----------------------------------------------------------


def test_shape_matches_axes_and_axes_follow_documented_steps():
    result = run_kde(_dataset(_blob(CENTRE_A, 10)), FAST)
    p = result.params
    assert result.density.shape == (result.grid_lat.size, result.grid_lon.size)
    assert result.grid_lat.dtype == result.grid_lon.dtype == result.density.dtype == np.float64
    ext = p["grid_extent"]
    mean_lat = (ext["south"] + ext["north"]) / 2
    assert p["lat_step_deg"] == pytest.approx(100 / 110_540, rel=1e-12)
    assert p["lon_step_deg"] == pytest.approx(100 / (111_320 * math.cos(math.radians(mean_lat))), rel=1e-12)
    np.testing.assert_allclose(np.diff(result.grid_lat), p["lat_step_deg"], rtol=1e-9)
    np.testing.assert_allclose(np.diff(result.grid_lon), p["lon_step_deg"], rtol=1e-9)
    assert result.grid_lat[0] == ext["south"] and result.grid_lon[0] == ext["west"]
    assert ext["north"] <= result.grid_lat[-1] < ext["north"] + p["lat_step_deg"]
    assert ext["east"] <= result.grid_lon[-1] < ext["east"] + p["lon_step_deg"]


def test_data_extent_grid_is_padded_by_three_bandwidths():
    result = run_kde(_dataset([CENTRE_A]), FAST)
    ext = result.params["grid_extent"]
    assert result.params["grid_source"] == "data_extent_padded"
    assert CENTRE_A[0] - ext["south"] == pytest.approx(3 * 300 / 110_540, rel=1e-9)
    assert ext["north"] - CENTRE_A[0] == pytest.approx(3 * 300 / 110_540, rel=1e-9)


def test_array_orientation_rows_are_latitude_columns_are_longitude():
    """Wide-but-short study area: many more longitude columns than latitude rows,
    and each density[i, j] equals an independent KDE evaluated at (grid_lat[i], grid_lon[j])."""
    area = StudyArea("strip", min_lat=23.015, max_lat=23.025, min_lon=72.540, max_lon=72.600)
    points = [CENTRE_A, (23.0230, 72.5900)]
    result = run_kde(_dataset(points), FAST, study_area=area)
    assert result.density.shape[1] > 4 * result.density.shape[0]
    reference = KernelDensity(bandwidth=300 / EARTH_RADIUS_M, metric="haversine", algorithm="ball_tree")
    reference.fit(np.radians(points))
    for i, j in [(0, result.grid_lon.size - 1), (result.grid_lat.size - 1, 0), (3, 17), (7, 40)]:
        expected = np.exp(reference.score_samples(np.radians([[result.grid_lat[i], result.grid_lon[j]]])))[0]
        assert result.density[i, j] == pytest.approx(expected, rel=1e-9)


def test_study_area_defines_grid_and_outside_points_still_contribute():
    area = StudyArea("box", min_lat=23.010, max_lat=23.030, min_lon=72.560, max_lon=72.580)
    inside_only = run_kde(_dataset([CENTRE_A]), FAST, study_area=area)
    with_outside = run_kde(_dataset([CENTRE_A, (23.031, 72.570)]), FAST, study_area=area)   # just north of box
    assert inside_only.params["grid_source"] == "study_area"
    assert inside_only.params["grid_extent"] == {"south": 23.010, "north": 23.030, "west": 72.560, "east": 72.580}
    assert with_outside.density[-1].max() > inside_only.density[-1].max()   # northern edge gets mass from outside


# --- parameters and limits ---------------------------------------------------------------


@pytest.mark.parametrize("field", ["bandwidth_m", "grid_cell_m"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, 3e7])
def test_invalid_bandwidth_or_cell_size_raises(field, bad):
    with pytest.raises(AnalysisError, match=field):
        run_kde(_dataset([CENTRE_A]), KDEParams(**{field: bad}))


@pytest.mark.parametrize("field", ["bandwidth_m", "grid_cell_m"])
def test_non_positive_bandwidth_or_cell_rejected_at_construction(field):
    with pytest.raises(ValueError):
        KDEParams(**{field: 0})


@pytest.mark.parametrize("q", [0.0, 1.0, -0.1, 1.5, float("nan"), True])
def test_quantile_outside_open_interval_is_rejected(q):
    # KDEParams construction already refuses these...
    with pytest.raises(ValueError):
        KDEParams(high_density_quantile=q)
    # ...and run_kde re-checks in case a params object bypasses construction.
    params = KDEParams(bandwidth_m=300, grid_cell_m=100)
    object.__setattr__(params, "high_density_quantile", q)
    with pytest.raises(AnalysisError, match="high_density_quantile"):
        run_kde(_dataset([CENTRE_A]), params)


def test_grid_cell_limit_refuses_before_computing():
    with pytest.raises(AnalysisError, match=r"400 cells exceeds the limit of 100\..*Increase grid_cell_m"):
        run_kde(_dataset(_blob(CENTRE_A, 5)), FAST, max_cells=100)


def test_default_cell_limit_blocks_continental_grid():
    far_apart = [(10.0, 70.0), (30.0, 90.0)]                    # ~3,000 km apart at 100 m cells
    with pytest.raises(AnalysisError, match=f"{MAX_GRID_CELLS:,}"):
        run_kde(_dataset(far_apart), FAST)


def test_polar_grid_is_refused():
    with pytest.raises(AnalysisError, match="85"):
        run_kde(_dataset([(84.999, 10.0)]), FAST)


# --- input contracts -----------------------------------------------------------------------


def test_unusable_dataset_raises_analysis_error():
    raw = pd.DataFrame({"incident_id": ["", "B"], "latitude": ["1", "x"], "longitude": ["2", "2"]}, dtype=str)
    unusable = validate_and_clean(raw, "synthetic")
    with pytest.raises(AnalysisError, match="unusable"):
        run_kde(unusable, FAST)
    with pytest.raises(AnalysisError, match="unusable"):
        estimate_density(unusable, AnalysisConfig(kde=FAST))


def test_non_finite_coordinates_in_hand_built_dataset_raise():
    dataset = _dataset([CENTRE_A, CENTRE_B])
    dataset.frame.loc[dataset.frame.index[0], "longitude"] = np.inf
    with pytest.raises(AnalysisError, match="non-finite"):
        run_kde(dataset, FAST)


@pytest.mark.parametrize("column,value", [("latitude", 95.0), ("latitude", -90.5), ("longitude", 181.0)])
def test_out_of_range_coordinates_in_hand_built_dataset_raise(column, value):
    dataset = _dataset([CENTRE_A, CENTRE_B])
    dataset.frame.loc[dataset.frame.index[1], column] = value
    with pytest.raises(AnalysisError, match="out-of-range"):
        run_kde(dataset, FAST)


def test_empty_dataset_raises_analysis_error():
    empty = validate_and_clean(pd.DataFrame(columns=["incident_id", "latitude", "longitude"], dtype=str), "s")
    assert empty.report.is_usable is False
    with pytest.raises(AnalysisError, match="unusable"):
        run_kde(empty, FAST)


def test_grid_value_sum_is_not_meaningful_but_area_weighted_sum_is():
    """Halving the cell size ~quadruples the plain sum; the area-weighted sum stays ~1."""
    area = StudyArea("wide", min_lat=22.995, max_lat=23.045, min_lon=72.545, max_lon=72.595)
    sums = {}
    for cell in (50, 25):
        r = run_kde(_dataset(_blob(CENTRE_A, 10)), KDEParams(bandwidth_m=300, grid_cell_m=cell), study_area=area)
        p = r.params
        cell_sr = math.radians(p["lat_step_deg"]) * math.radians(p["lon_step_deg"]) * np.cos(np.radians(r.grid_lat))
        sums[cell] = (r.density.sum(), float((r.density * cell_sr[:, None]).sum()))
    assert sums[25][0] == pytest.approx(4 * sums[50][0], rel=0.05)
    assert sums[50][1] == pytest.approx(1.0, rel=5e-3) and sums[25][1] == pytest.approx(1.0, rel=5e-3)


def test_area_weighted_sum_is_below_one_when_grid_cuts_off_mass():
    half = StudyArea("half", min_lat=22.995, max_lat=23.045, min_lon=72.570, max_lon=72.595)  # west half cut off
    r = run_kde(_dataset([CENTRE_A]), KDEParams(bandwidth_m=300, grid_cell_m=25), study_area=half)
    p = r.params
    cell_sr = math.radians(p["lat_step_deg"]) * math.radians(p["lon_step_deg"]) * np.cos(np.radians(r.grid_lat))
    assert float((r.density * cell_sr[:, None]).sum()) == pytest.approx(0.5, abs=0.02)


def test_single_point_is_valid_and_peaks_at_the_point():
    result = run_kde(_dataset([CENTRE_A]), FAST)
    peak_lat, peak_lon = _peak(result)
    assert abs(peak_lat - CENTRE_A[0]) <= result.params["lat_step_deg"]
    assert abs(peak_lon - CENTRE_A[1]) <= result.params["lon_step_deg"]
    assert result.params["n_points"] == 1


def test_repeated_coordinates_keep_shape_but_add_relative_weight():
    single = run_kde(_dataset([CENTRE_A]), FAST)
    repeated = run_kde(_dataset([CENTRE_A] * 5), FAST)
    np.testing.assert_allclose(repeated.density, single.density, rtol=1e-12)   # normalised: same surface
    mixed = run_kde(_dataset([CENTRE_A] * 4 + [CENTRE_B]), FAST)
    assert _value_at(mixed, *CENTRE_A) == pytest.approx(4 * _value_at(mixed, *CENTRE_B), rel=0.02)


def test_input_dataset_is_not_mutated():
    dataset = _dataset(_blob(CENTRE_A, 8), index=[90, 3, 41, 7, 0, 12, 5, 66])
    before = dataset.frame.copy(deep=True)
    run_kde(dataset, FAST)
    pd.testing.assert_frame_equal(dataset.frame, before)


def test_results_are_deterministic():
    dataset = _dataset(_blob(CENTRE_A, 15) + _blob(CENTRE_B, 9))
    first, second = run_kde(dataset, FAST), run_kde(dataset, FAST)
    assert np.array_equal(first.density, second.density)
    assert np.array_equal(first.grid_lat, second.grid_lat) and np.array_equal(first.grid_lon, second.grid_lon)
    assert first.high_density_threshold == second.high_density_threshold


def test_non_consecutive_source_index_gives_identical_result():
    points = _blob(CENTRE_A, 12)
    plain = run_kde(_dataset(points), FAST)
    gapped = run_kde(_dataset(points, index=[1000, 3, 57, 8, 2, 999, 41, 12, 77, 5, 64, 30]), FAST)
    assert np.array_equal(plain.density, gapped.density)


# --- interpretation of values ----------------------------------------------------------------


@pytest.mark.parametrize("n", [10, 40])
def test_density_integrates_to_one_over_the_sphere_not_to_the_count(n):
    """Values are a probability density per steradian: sum(density * cell area in sr) ~= 1
    whatever the number of incidents, so they are relative scores, not counts."""
    area = StudyArea("wide", min_lat=22.995, max_lat=23.045, min_lon=72.545, max_lon=72.595)
    result = run_kde(_dataset(_blob(CENTRE_A, n)), KDEParams(bandwidth_m=300, grid_cell_m=25), study_area=area)
    p = result.params
    cell_sr = math.radians(p["lat_step_deg"]) * math.radians(p["lon_step_deg"]) * np.cos(np.radians(result.grid_lat))
    integral = float((result.density * cell_sr[:, None]).sum())
    assert integral == pytest.approx(1.0, rel=5e-3)
    assert result.density.sum() != pytest.approx(n, rel=0.5)


def test_density_units_are_documented_as_relative_not_counts_or_rates():
    units = run_kde(_dataset([CENTRE_A]), FAST).params["density_units"]
    assert "relative density score" in units and "steradian" in units
    assert "not an incident count" in units and "not a per-km2 rate" in units


def test_high_density_threshold_is_grid_quantile_not_dbscan_threshold():
    result = run_kde(_dataset(_blob(CENTRE_A, 20)), KDEParams(bandwidth_m=300, grid_cell_m=100, high_density_quantile=0.9))
    assert result.high_density_threshold == np.quantile(result.density, 0.9)
    assert (result.density >= result.high_density_threshold).mean() == pytest.approx(0.1, abs=0.01)
    assert "min_incidents" not in result.params


def test_params_record_conversion_and_grid():
    p = run_kde(_dataset([CENTRE_A]), FAST).params
    assert p["bandwidth_m"] == 300.0 and p["bandwidth_rad"] == 300.0 / EARTH_RADIUS_M
    assert (p["kernel"], p["metric"], p["algorithm"], p["grid_cell_m"]) == ("gaussian", "haversine", "ball_tree", 100.0)


def test_controller_uses_config_kde_and_study_area():
    area = StudyArea("box", min_lat=23.010, max_lat=23.030, min_lon=72.560, max_lon=72.580)
    result = estimate_density(_dataset([CENTRE_A]), AnalysisConfig(kde=FAST, study_area=area))
    assert result.params["grid_source"] == "study_area" and result.params["bandwidth_m"] == 300.0


# --- existing parameter-object checks ---------------------------------------------------------


def test_kde_params_reject_bad_quantile():
    with pytest.raises(ValueError):
        KDEParams(high_density_quantile=1.0)


def test_kde_params_reject_unsupported_kernel():
    with pytest.raises(ValueError):
        KDEParams(kernel="triweight")
