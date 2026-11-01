"""Summary page layout and Key Findings tests (Stage 10B Phase 4.3, redesign Stage 5).

Layout and wording only; every value comes from the unchanged analysis modules.
Synthetic data and temporary history/reports locations only.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from modules import ui_theme
from config.settings import DEFAULT_ANALYSIS_CONFIG
from modules.app_controller import cluster_dataset, estimate_density, summarize_results
from modules.contracts import AnalysisError
from modules.dashboard import FINDINGS_NOTE, KDE_DISCLAIMER, SUMMARY_TABS, SYNTHETIC_NOTICE, is_synthetic_source, key_findings
from modules.data_validator import validate_and_clean

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page('Summary')\n"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")


def _dataset(name="field_export.csv"):
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    n = len(points)
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(n)],
                        "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points],
                        "severity": (["major", "minor"] * n)[:n], "incident_type": (["crash", "near-miss"] * n)[:n],
                        "incident_date": [f"2024-0{1 + i % 6}-1{i % 9}" for i in range(n)]}, dtype=str)
    return validate_and_clean(raw, name)


def _app(dataset):
    at = AppTest.from_string(SCRIPT, default_timeout=120)
    at.session_state["dataset"] = dataset
    return at.run()


def test_sections_are_tabs_and_keep_all_content():
    at = _app(_dataset())
    assert not at.exception
    assert [t.label for t in at.tabs] == list(SUMMARY_TABS) == ["Method Comparison", "Distributions", "Notes & Limitations"]
    assert [s.value for s in at.subheader][:6] == ["Geographic overview", "Cluster analysis", "Density analysis",
                                                   "KDE results", "Key findings", "Save to history"]
    assert {"DBSCAN vs KDE (descriptive comparison)", "Incidents by category and date", "Notes and caveats"} <= \
           {s.value for s in at.subheader}
    assert len(at.dataframe) == 2 and len(at.get("plotly_chart")) == 3


def test_metrics_keep_their_order_and_values():
    at = _app(_dataset())
    density = at.session_state[dashboard.CACHE_KEY]["density"]
    assert [(m.label, m.value) for m in at.metric] == [
        ("Accepted incidents", "19 of 19"), ("Rejected", "0"), ("Clusters", "2"), ("Candidate hotspots", "1"),
        ("Noise incidents", "1"), ("Noise share", "5.3%"),
        ("Grid cells", f"{density.density.shape[0]} × {density.density.shape[1]}"), ("Bandwidth", "300 m"),
        ("Peak relative score", f"{density.density.max():.4g}")]


def test_save_is_a_primary_action_and_reports_still_follow():
    at = _app(_dataset())
    assert at.button(key="save_run").proto.type == "primary"
    at.button(key="save_run").click().run()
    assert any("Saved to the history" in s.value for s in at.success)
    assert at.button(key="generate_reports").proto.type == "primary"


def test_synthetic_notice_follows_the_file_name():
    assert is_synthetic_source("synthetic_demo.csv") and is_synthetic_source("My_SYNTHETIC_set.csv")
    assert not is_synthetic_source("field_export.csv")
    assert SYNTHETIC_NOTICE in [i.value for i in _app(_dataset("synthetic_demo.csv")).info]
    assert SYNTHETIC_NOTICE not in [i.value for i in _app(_dataset()).info]
    assert "not real-world incident statistics" in SYNTHETIC_NOTICE


def test_bar_chart_layout_uses_the_shared_theme():
    layout = ui_theme.bar_chart_layout("Incidents by severity", "All accepted incidents", "Severity")
    assert layout["title"]["text"] == "Incidents by severity<br><sup>All accepted incidents</sup>"
    assert layout["template"].layout.font.family == ui_theme.FONT_STACK
    assert layout["showlegend"] is False and layout["height"] > ui_theme.CHART_HEIGHT_PX


def test_no_hard_coded_chart_blue_remains():
    source = (ROOT / "modules" / "dashboard.py").read_text(encoding="utf-8")
    assert "#2e86c1" not in source.lower()
    assert 'marker_color=ACCENT' in source


def test_summary_css_is_static_and_scoped_to_summary_keys():
    css = ui_theme.SHELL_CSS
    assert f".st-key-{ui_theme.SUMMARY_KPI_KEY} > *" in css
    assert f'[class*="st-key-{ui_theme.PANEL_PREFIX}"]' in css
    assert "<" not in css


# --- redesign Stage 5 ----------------------------------------------------------------------------


def _results(dataset, clusters=True, density=True):
    c = cluster_dataset(dataset, DEFAULT_ANALYSIS_CONFIG) if clusters else None
    k = estimate_density(dataset, DEFAULT_ANALYSIS_CONFIG) if density else None
    return {"clusters": c, "density": k, "summary": summarize_results(dataset, c, k), "config": DEFAULT_ANALYSIS_CONFIG}


def test_page_title_and_status_bar():
    at = _app(_dataset())
    assert [h.value for h in at.header] == ["Spatial Analysis Overview"]
    assert any("field\\_export\\.csv" in m.value for m in at.main.markdown)
    assert any("19 rows · 19 accepted · 0 rejected" in c.value for c in at.main.caption)
    assert any(":green-badge[Complete]" in m.value for m in at.main.markdown)


def test_both_existing_interactive_maps_are_on_the_page(monkeypatch):
    drawn = {}
    monkeypatch.setattr(dashboard, "st_folium", lambda fmap, **kw: drawn.update({kw["key"]: (fmap, kw["returned_objects"])}))
    dataset = _dataset()
    results = _results(dataset)
    dashboard._render_geographic_overview(results)
    dashboard._render_density_overview(results)
    assert set(drawn) == {"summary_cluster_map", "summary_density_map"}
    names = [type(c).__name__ for c in drawn["summary_cluster_map"][0]._children.values()]
    assert "DarkMapStyle" in names and "MapLegend" in names
    assert "ImageOverlay" in [type(c).__name__ for c in drawn["summary_density_map"][0]._children.values()]


def test_cluster_section_shows_existing_facts_only():
    dataset = _dataset()
    results = _results(dataset)
    rows = dashboard.cluster_rows_html(results["clusters"], centres=True)
    for c in results["clusters"].clusters:
        assert f"Cluster {c.cluster_label}" in rows and f"{c.incident_count:,} incidents" in rows
        assert f"{c.radius_m:,.0f} m radius" in rows and f"Centre {c.centroid_lat:.5f}, {c.centroid_lon:.5f}" in rows
    assert rows.count("Candidate hotspot") == sum(c.is_candidate_hotspot for c in results["clusters"].clusters)
    assert "Centre" not in dashboard.cluster_rows_html(results["clusters"])    # Clusters page unchanged


def test_density_section_explains_relative_scores():
    at = _app(_dataset())
    assert KDE_DISCLAIMER in [i.value for i in at.info]
    assert any("not automatically a DBSCAN cluster" in c.value for c in at.main.caption)


def test_every_finding_comes_from_the_results():
    dataset = _dataset()
    results = _results(dataset)
    clusters, density, mc = results["clusters"], results["density"], results["summary"].method_comparison
    largest = max(clusters.clusters, key=lambda c: c.incident_count)
    row, col = np.unravel_index(int(np.argmax(density.density)), density.density.shape)
    findings = {title: text for _, title, text in key_findings(dataset, results)}
    assert list(findings) == ["Data analysed", "Clusters", "Noise", "Candidate hotspots", "Density peak", "DBSCAN and KDE"]
    assert findings["Data analysed"] == "19 of 19 rows were accepted and analysed; 0 rejected."
    assert findings["Clusters"] == (f"DBSCAN found 2 clusters holding {19 - clusters.noise_count} of 19 incidents. "
                                    f"The largest is Cluster {largest.cluster_label}, with {largest.incident_count} incidents.")
    assert findings["Noise"].startswith("1 of 19 incidents (5.3%) are noise")
    assert findings["Candidate hotspots"].startswith("1 cluster met the size rule of at least 10 incidents: Cluster 0.")
    assert f"{density.density.max():.4g}" in findings["Density peak"]
    assert f"{density.grid_lat[row]:.5f}, {density.grid_lon[col]:.5f}" in findings["Density peak"]
    assert (f"{mc.clustered_high} of {mc.clustered_eligible} clustered incidents and "
            f"{mc.noise_high} of {mc.noise_eligible} noise incidents") in findings["DBSCAN and KDE"]


def test_findings_never_claim_significance_or_predict():
    dataset = _dataset()
    text = " ".join(t for _, _, t in key_findings(dataset, _results(dataset))).lower()
    for word in ("statistically significant", "will ", "predict", "forecast", "risk", "trend"):
        assert word not in text
    assert "statistical significance" in FINDINGS_NOTE and "predict future incidents" in FINDINGS_NOTE
    assert FINDINGS_NOTE in [c.value for c in _app(dataset).main.caption]


def test_findings_skip_analyses_that_did_not_run():
    dataset = _dataset()
    assert [t for _, t, _ in key_findings(dataset, _results(dataset, clusters=False))] == ["Data analysed", "Density peak"]
    assert [t for _, t, _ in key_findings(dataset, _results(dataset, density=False))] == [
        "Data analysed", "Clusters", "Noise", "Candidate hotspots"]


def test_findings_handle_no_clusters():
    points = [(23.0 + 0.05 * i, 72.5 + 0.05 * i) for i in range(4)]
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(4)], "latitude": [repr(p[0]) for p in points],
                        "longitude": [repr(p[1]) for p in points]}, dtype=str)
    dataset = validate_and_clean(raw, "spread.csv")
    findings = {title: text for _, title, text in key_findings(dataset, _results(dataset))}
    assert findings["Clusters"] == "DBSCAN found no clusters with these parameters; every incident is noise."
    assert findings["Candidate hotspots"] == "No cluster met the size rule of at least 10 incidents."
    assert findings["Noise"].startswith("4 of 4 incidents (100.0%)")


def test_page_stays_usable_when_each_analysis_fails(monkeypatch):
    def failing(*args, **kwargs):
        raise AnalysisError("simulated failure")
    monkeypatch.setattr(dashboard, "cluster_dataset", failing)
    at = _app(_dataset())
    assert not at.exception
    assert any("needs a DBSCAN result" in i.value for i in at.info)
    monkeypatch.undo()
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", dashboard.HISTORY_DB_PATH)
    monkeypatch.setattr(dashboard, "estimate_density", failing)
    at = _app(_dataset())
    assert not at.exception and any("needs a KDE result" in i.value for i in at.info)


def test_rendering_the_page_leaves_results_untouched():
    dataset = _dataset()
    first = _results(dataset)
    labels = first["clusters"].labeled_frame["cluster_label"].to_numpy().copy()
    values = first["density"].density.copy()
    key_findings(dataset, first)
    dashboard.cluster_rows_html(first["clusters"], centres=True)
    assert np.array_equal(first["clusters"].labeled_frame["cluster_label"].to_numpy(), labels)
    assert np.array_equal(first["density"].density, values)
