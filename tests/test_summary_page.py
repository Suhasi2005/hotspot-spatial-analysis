"""Summary page layout tests (Stage 10B Phase 4.3).

Layout and wording only; every value comes from the unchanged analysis modules.
Synthetic data and temporary history/reports locations only.
"""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from modules import ui_theme
from modules.dashboard import SUMMARY_TABS, SYNTHETIC_NOTICE, is_synthetic_source
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
    assert [s.value for s in at.subheader][:2] == ["Overview", "Save to history"]
    assert {"DBSCAN vs KDE (descriptive comparison)", "Incidents by category and date", "Notes and caveats"} <= \
           {s.value for s in at.subheader}
    assert len(at.dataframe) == 2 and len(at.get("plotly_chart")) == 3


def test_metrics_keep_their_order_and_values():
    at = _app(_dataset())
    assert [(m.label, m.value) for m in at.metric] == [
        ("Rows in file", "19"), ("Accepted incidents", "19"), ("Rejected", "0"), ("Analysis status", "Complete"),
        ("Clusters", "2"), ("Candidate hotspots", "1"), ("Noise incidents", "1 of 19"), ("Noise share", "5.3%")]


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
    assert f'[class*="st-key-{ui_theme.SUMMARY_PANEL_PREFIX}"]' in css
    assert "<" not in css and "@media" not in css
