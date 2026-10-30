"""Analysis-page layout tests (Stage 10B Phase 3): Data, Clusters and Density pages.

Layout and wording only; the analysis values come from the unchanged modules.
Synthetic data and temporary history/reports locations only.
"""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from config.settings import DEFAULT_ANALYSIS_CONFIG
from modules.contracts import AnalysisError
from modules.dashboard import FILTERS_LABEL, KDE_DISCLAIMER, NOT_RUN, validation_status
from modules.data_validator import validate_and_clean

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page(PAGE)\n"
VALIDATION_SCRIPT = (f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nimport streamlit as st\n"
                     "from modules.dashboard import _render_validation\n_render_validation(st.session_state['dataset'])\n")


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")


def _dataset(rejected=0, usable=True):
    if not usable:
        return validate_and_clean(pd.DataFrame({"incident_id": [""], "latitude": ["1"], "longitude": ["2"]}, dtype=str), "bad.csv")
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    ids = [f"P{i}" for i in range(len(points))]
    lats = [repr(p[0]) for p in points]
    lons = [repr(p[1]) for p in points]
    for i in range(rejected):
        ids.append(f"R{i}"), lats.append("999"), lons.append("72.5")       # latitude out of range
    raw = pd.DataFrame({"incident_id": ids, "latitude": lats, "longitude": lons}, dtype=str)
    return validate_and_clean(raw, "synthetic_pages.csv")


def _app(page, dataset):
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr(page)), default_timeout=120)
    at.session_state["dataset"] = dataset
    return at.run()


def _validation(dataset):
    at = AppTest.from_string(VALIDATION_SCRIPT, default_timeout=120)
    at.session_state["dataset"] = dataset
    return at.run()


def _metrics(at):
    return {m.label: m.value for m in at.metric}


# --- Data page -------------------------------------------------------------------------------


def test_validation_status_values():
    assert validation_status(_dataset().report) == "Ready"
    assert validation_status(_dataset(rejected=2).report) == "Ready with rejections"
    assert validation_status(_dataset(usable=False).report) == "Unusable"


def test_validation_summary_tabs_and_success():
    at = _validation(_dataset())
    assert not at.exception
    assert _metrics(at) == {"Rows in file": "19", "Accepted": "19", "Rejected": "0", "Validation status": "Ready"}
    assert [t.label for t in at.tabs] == ["Incident Map", "Validation Issues (0)", "Data Preview"]
    assert any("All rows passed validation." in s.value and "ready for analysis" in s.value for s in at.success)
    assert any("synthetic\\_pages\\.csv" in c.value for c in at.caption)     # file name, escaped


def test_validation_with_rejected_rows_shows_warning_and_issues():
    at = _validation(_dataset(rejected=2))
    m = _metrics(at)
    assert (m["Rows in file"], m["Accepted"], m["Rejected"]) == ("21", "19", "2")
    assert m["Validation status"] == "Ready with rejections"
    assert any("2 row(s) were rejected" in w.value for w in at.warning)
    assert at.tabs[1].label.startswith("Validation Issues (") and len(at.dataframe) == 2   # issues + preview


def test_unusable_dataset_shows_error_and_no_preview():
    at = _validation(_dataset(usable=False))
    assert _metrics(at)["Validation status"] == "Unusable"
    assert any("unusable" in e.value for e in at.error)
    assert any("No accepted rows to preview." in c.value for c in at.caption)


# --- Clusters page ---------------------------------------------------------------------------


def test_clusters_page_layout_and_explanation():
    at = _app("Clusters (DBSCAN)", _dataset())
    assert not at.exception
    assert [e.label for e in at.sidebar.expander][-1] == FILTERS_LABEL
    assert FILTERS_LABEL == "Display filters — visualization only; analysis results remain unchanged."
    assert [t.label for t in at.tabs] == ["Table", "Cluster sizes"]
    text = " ".join(m.value for m in at.main.markdown)
    default = DEFAULT_ANALYSIS_CONFIG.hotspot.min_incidents
    assert f"at least **{default}** incidents (min_incidents)" in text
    assert "does not test statistical significance" in text and "noise" in text
    assert "significant hotspot" not in text.lower()


def test_clusters_explanation_follows_min_incidents_parameter():
    at = _app("Clusters (DBSCAN)", _dataset())
    at.number_input(key="p_min_incidents").set_value(20).run()
    text = " ".join(m.value for m in at.main.markdown)
    assert "at least **20** incidents" in text
    assert _metrics(at)["Candidate hotspots"] == "0"


def test_clusters_filters_still_display_only():
    at = _app("Clusters (DBSCAN)", _dataset())
    at.checkbox(key="f_show_noise").uncheck().run()
    assert any("Showing 18 of 19" in c.value for c in at.caption)
    assert _metrics(at)["Noise incidents"] == "1 of 19" and _metrics(at)["Noise share"] == "5.3%"


def test_clusters_kpis_not_run_when_dbscan_fails(monkeypatch):
    def failing(*args, **kwargs):
        raise AnalysisError("simulated DBSCAN failure")
    monkeypatch.setattr(dashboard, "cluster_dataset", failing)
    at = _app("Clusters (DBSCAN)", _dataset())
    assert set(_metrics(at).values()) == {NOT_RUN}
    assert any("DBSCAN failed" in e.value for e in at.error)


# --- Density page ----------------------------------------------------------------------------


def test_density_page_disclaimer_and_parameter_expander():
    at = _app("Density (KDE)", _dataset())
    assert not at.exception
    assert KDE_DISCLAIMER == ("KDE values are relative density scores. They are not incident counts or "
                              "incidents per square kilometre.")
    assert KDE_DISCLAIMER in [i.value for i in at.info]
    assert "All KDE parameters" in [e.label for e in at.main.expander]
    assert any("Bandwidth 300 m" in c.value and "Threshold quantile" in c.value for c in at.caption)
