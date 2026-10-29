"""Dashboard tests: pure helpers plus headless Streamlit page runs (AppTest).

Synthetic data only. Maps are custom components that AppTest does not render;
their content is covered in test_map_visualization.py.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from config.settings import DEFAULT_ANALYSIS_CONFIG, AnalysisConfig, DBSCANParams
from modules.app_controller import cluster_dataset, estimate_density, summarize_results
from modules.contracts import CLUSTER_LABEL_COLUMN, AnalysisError
from modules.dashboard import CACHE_KEY, MISSING_LABEL, analysis_cache_key, display_mask
from modules.data_validator import validate_and_clean
from modules.spatial_statistics import incidents_by_period, summarize

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page(PAGE)\n"


def _dataset(n_a=12, n_b=6, optional=True, dates=None, index=None):
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(n_a)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(n_b)] + [(23.1000, 72.6500)]
    n = len(points)
    columns = {"incident_id": [f"P{i}" for i in range(n)],
               "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]}
    if optional:
        columns["severity"] = (["major", "minor", ""] * n)[:n]
        columns["incident_type"] = (["crash", "near-miss"] * n)[:n]
        columns["incident_date"] = dates or [f"2024-0{1 + i % 6}-1{i % 9}" for i in range(n)]
    raw = pd.DataFrame(columns, dtype=str)
    if index is not None:
        raw.index = index
    return validate_and_clean(raw, "synthetic")


def _app(page, dataset=None):
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr(page)), default_timeout=120)
    if dataset is not None:
        at.session_state["dataset"] = dataset
    return at.run()


def _messages(at):
    return {"info": [e.value for e in at.info], "warning": [e.value for e in at.warning],
            "error": [e.value for e in at.error], "caption": [e.value for e in at.caption]}


# --- display_mask (display-only filters) -------------------------------------------------


def _labeled(dataset):
    return cluster_dataset(dataset, DEFAULT_ANALYSIS_CONFIG).labeled_frame


def test_display_mask_filters_by_category_with_missing_label():
    frame = _labeled(_dataset())
    sev = frame["severity"].astype(object)
    mask = display_mask(frame, severities={"major", MISSING_LABEL})
    assert np.array_equal(mask, (sev.isna() | (sev == "major")).to_numpy())
    both = display_mask(frame, severities={"major"}, incident_types={"crash"})
    assert np.array_equal(both, ((sev == "major") & (frame["incident_type"].astype(object) == "crash")).to_numpy())
    assert display_mask(frame).all()                                      # no filters -> everything


def test_display_mask_noise_and_candidate_toggles():
    frame = _labeled(_dataset())
    labels = frame[CLUSTER_LABEL_COLUMN].to_numpy()
    assert np.array_equal(display_mask(frame, show_noise=False), labels != -1)
    assert np.array_equal(display_mask(frame, candidate_labels={labels[0]}), labels == labels[0])
    assert not display_mask(frame, candidate_labels=set()).any()


def test_display_mask_ignores_absent_columns_and_does_not_mutate():
    frame = _labeled(_dataset(optional=False))
    before = frame.copy(deep=True)
    assert display_mask(frame, severities={"major"}, incident_types={"x"}).all()
    pd.testing.assert_frame_equal(frame, before)


def test_cache_key_changes_with_any_parameter():
    base = analysis_cache_key(DEFAULT_ANALYSIS_CONFIG)
    assert base == analysis_cache_key(AnalysisConfig())
    assert base != analysis_cache_key(AnalysisConfig(dbscan=DBSCANParams(eps_m=251.0)))


# --- controller wrapper and date helper -----------------------------------------------------


def test_summarize_results_delegates_to_summarize():
    dataset = _dataset()
    clusters = cluster_dataset(dataset, DEFAULT_ANALYSIS_CONFIG)
    density = estimate_density(dataset, DEFAULT_ANALYSIS_CONFIG)
    assert summarize_results(dataset, clusters, density) == summarize(dataset, clusters, density)
    assert summarize_results(dataset, None, None) == summarize(dataset, None, None)


def test_summarize_results_keeps_stage6_validation():
    raw = pd.DataFrame({"incident_id": [""], "latitude": ["1"], "longitude": ["2"]}, dtype=str)
    with pytest.raises(AnalysisError, match="unusable"):
        summarize_results(validate_and_clean(raw, "s"), None, None)


@pytest.mark.parametrize(
    "dates,period,expected",
    [
        (["2024-01-05", "2024-01-05", "2024-01-07"], "day", [2, 0, 1]),
        (["2024-01-31", "2024-04-01", "2024-04-15"], "month", [1, 0, 0, 2]),   # 75 days
        (["2021-06-01", "2024-02-01", "2024-12-31"], "year", [1, 0, 0, 2]),
    ],
)
def test_incidents_by_period_rule_and_zero_filled_gaps(dates, period, expected):
    raw = pd.DataFrame({"incident_id": ["a", "b", "c"], "latitude": ["1"] * 3, "longitude": ["2"] * 3,
                        "incident_date": dates}, dtype=str)
    result = incidents_by_period(validate_and_clean(raw, "s"))
    assert result["period"] == period and result["column_present"] is True
    assert result["counts"]["incident_count"].tolist() == expected
    assert result["counts"]["incident_count"].sum() == result["dated_incidents"] == 3
    assert result["counts"]["period_start"].is_monotonic_increasing


def test_incidents_by_period_boundaries_between_day_month_year():
    def period_for(last):
        raw = pd.DataFrame({"incident_id": ["a", "b"], "latitude": ["1"] * 2, "longitude": ["2"] * 2,
                            "incident_date": ["2024-01-01", last]}, dtype=str)
        return incidents_by_period(validate_and_clean(raw, "s"))["period"]
    assert period_for("2024-03-03") == "day"          # 62 days
    assert period_for("2024-03-04") == "month"        # 63 days
    assert period_for("2027-01-01") == "month"        # 1096 days
    assert period_for("2027-01-02") == "year"         # 1097 days


def test_incidents_by_period_missing_and_absent_dates():
    raw = pd.DataFrame({"incident_id": ["a", "b", "c"], "latitude": ["1"] * 3, "longitude": ["2"] * 3,
                        "incident_date": ["2024-01-05", "", "05/01/2024"]}, dtype=str)
    result = incidents_by_period(validate_and_clean(raw, "s"))
    assert (result["dated_incidents"], result["missing_dates"]) == (1, 2)   # blank + non-ISO are NaT
    all_missing = pd.DataFrame({"incident_id": ["a"], "latitude": ["1"], "longitude": ["2"], "incident_date": [""]}, dtype=str)
    none = incidents_by_period(validate_and_clean(all_missing, "s"))
    assert none["period"] is None and none["counts"].empty and none["missing_dates"] == 1
    absent = incidents_by_period(_dataset(optional=False))
    assert absent["column_present"] is False and absent["counts"].empty


def test_incidents_by_period_converts_time_zones_to_utc():
    raw = pd.DataFrame({"incident_id": ["a", "b"], "latitude": ["1"] * 2, "longitude": ["2"] * 2,
                        "incident_date": ["2024-01-01T23:30:00+00:00", "2024-01-02T02:00:00+05:30"]}, dtype=str)
    result = incidents_by_period(validate_and_clean(raw, "s"))
    assert result["period"] == "day" and result["counts"]["incident_count"].tolist() == [2]   # both 1 Jan UTC


def test_incidents_by_period_rejects_unusable_and_does_not_mutate():
    raw = pd.DataFrame({"incident_id": [""], "latitude": ["1"], "longitude": ["2"]}, dtype=str)
    with pytest.raises(AnalysisError):
        incidents_by_period(validate_and_clean(raw, "s"))
    dataset = _dataset()
    before = dataset.frame.copy(deep=True)
    incidents_by_period(dataset)
    pd.testing.assert_frame_equal(dataset.frame, before)


# --- pages (headless Streamlit) ---------------------------------------------------------------


@pytest.mark.parametrize("page", ["Clusters (DBSCAN)", "Density (KDE)", "Summary"])
def test_analysis_pages_without_a_dataset(page):
    at = _app(page)
    assert not at.exception
    assert any("No dataset loaded" in m for m in _messages(at)["info"])


@pytest.mark.parametrize("page", ["Clusters (DBSCAN)", "Density (KDE)", "Summary"])
def test_analysis_pages_with_an_unusable_dataset(page):
    raw = pd.DataFrame({"incident_id": [""], "latitude": ["1"], "longitude": ["2"]}, dtype=str)
    at = _app(page, validate_and_clean(raw, "s"))
    assert not at.exception
    assert any("unusable" in m for m in _messages(at)["warning"])
    assert CACHE_KEY not in at.session_state


def test_data_and_history_pages_still_render():
    data = _app("Data")
    assert not data.exception and [h.value for h in data.header] == ["Data"]
    history = _app("History & Reports")
    assert not history.exception and any("Not implemented yet" in m for m in _messages(history)["info"])


def test_clusters_page_with_valid_data():
    at = _app("Clusters (DBSCAN)", _dataset())
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Clusters"] == "2" and metrics["Candidate hotspots"] == "1"
    assert len(at.get("plotly_chart")) == 1 and len(at.dataframe) == 1
    assert any("Showing 19 of 19" in c for c in _messages(at)["caption"])


def test_density_page_with_valid_data():
    at = _app("Density (KDE)", _dataset())
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "not incident counts or incidents/km²" in text and "not statistically significant" in text
    params = at.dataframe[0].value
    assert "density units" in params["parameter"].tolist()


def test_summary_page_with_both_analyses_and_all_charts():
    at = _app("Summary", _dataset())
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Clusters"] == "2" and metrics["Noise share"] == "5.3%"
    assert len(at.get("plotly_chart")) == 3                              # severity, type, date
    table = at.dataframe[0].value
    assert table.loc["Total (eligible)", "Total (eligible)"] == 19
    notes = " ".join(m.value for m in at.markdown)
    assert "descriptive" in notes and "not establish statistical" in notes


def test_summary_page_without_optional_columns_shows_no_fabricated_charts():
    at = _app("Summary", _dataset(optional=False))
    assert not at.exception
    assert len(at.get("plotly_chart")) == 0
    captions = _messages(at)["caption"]
    assert any("No severity or incident_type column" in c for c in captions)
    assert any("No incident_date column" in c for c in captions)


def test_kde_failure_is_shown_and_summary_marks_comparison_unavailable():
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr("Summary")), default_timeout=120)
    at.session_state["dataset"] = _dataset()
    at.run()
    at.number_input(key="p_grid_cell_m").set_value(1.0).run()           # 1 m cells -> grid far above the cap
    assert not at.exception
    assert any("KDE did not run" in w and "exceeds the limit" in w for w in _messages(at)["warning"])
    assert any("needs both DBSCAN and KDE" in i for i in _messages(at)["info"])
    assert {m.label: m.value for m in at.metric}["Clusters"] == "2"     # DBSCAN still shown


def test_invalid_parameter_stops_analysis_with_clear_errors():
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr("Clusters (DBSCAN)")), default_timeout=120)
    at.session_state["dataset"] = _dataset()
    at.run()
    at.number_input(key="p_min_samples").set_value(0).run()
    assert not at.exception
    errors = _messages(at)["error"]
    assert any("Invalid parameter" in e and "min_samples" in e for e in errors)
    assert any("No analysis was run" in e for e in errors)


def test_filters_change_display_only_and_never_refit():
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr("Clusters (DBSCAN)")), default_timeout=120)
    at.session_state["dataset"] = _dataset()
    at.run()
    cache = at.session_state[CACHE_KEY]
    clusters_before, density_before = cache["clusters"], cache["density"]
    labels_before = clusters_before.labeled_frame[CLUSTER_LABEL_COLUMN].copy()

    at.multiselect(key="f_severity").set_value(["major"]).run()
    at.checkbox(key="f_show_noise").uncheck().run()
    at.checkbox(key="f_candidates_only").check().run()
    assert not at.exception
    after = at.session_state[CACHE_KEY]
    assert after["clusters"] is clusters_before and after["density"] is density_before   # no refit
    pd.testing.assert_series_equal(after["clusters"].labeled_frame[CLUSTER_LABEL_COLUMN], labels_before)
    shown = next(c for c in _messages(at)["caption"] if c.startswith("Showing"))
    assert shown != "Showing 19 of 19 accepted incidents under the current display filters."
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Clusters"] == "2" and metrics["Noise incidents"] == "1 of 19"        # analysis unchanged


def test_results_are_recomputed_when_parameters_or_dataset_change():
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr("Clusters (DBSCAN)")), default_timeout=120)
    first_dataset = _dataset()
    at.session_state["dataset"] = first_dataset
    at.run()
    first = at.session_state[CACHE_KEY]["clusters"]
    at.run()
    assert at.session_state[CACHE_KEY]["clusters"] is first                  # same inputs -> reused
    at.number_input(key="p_eps_m").set_value(300.0).run()
    second = at.session_state[CACHE_KEY]["clusters"]
    assert second is not first and second.params["eps_m"] == 300.0          # parameters changed -> recomputed
    at.session_state["dataset"] = _dataset(n_a=5)                            # new dataset object
    at.run()
    third = at.session_state[CACHE_KEY]
    assert third["dataset"] is not first_dataset and len(third["clusters"].labeled_frame) == 12


def test_cluster_page_with_non_consecutive_index():
    dataset = _dataset(index=list(range(100, 138, 2)))
    at = _app("Clusters (DBSCAN)", dataset)
    assert not at.exception
    assert list(at.session_state[CACHE_KEY]["clusters"].labeled_frame.index) == list(range(100, 138, 2))
