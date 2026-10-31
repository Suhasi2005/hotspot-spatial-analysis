"""Tables, empty states and History layout tests (Stage 10B Phase 4.4).

Display only: underlying frames and stored runs are checked to be unchanged.
Synthetic data and temporary history/reports locations only.
"""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from modules import ui_theme
from modules.dashboard import (
    HISTORY_PARAMETER_COLUMNS,
    HISTORY_RESULT_COLUMNS,
    TABLE_SCROLL_HINT,
    _history_row,
    _run_label,
    column_label,
)
from modules.data_validator import validate_and_clean
from modules.report_generator import CSV_SAFETY_WARNING

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page(PAGE)\n"
# Registers real pages the way app.py does, so the empty-state links can render.
LINKED_SCRIPT = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from modules.dashboard import PAGE_LINKS_KEY, PAGES, render_page
def page(): pass
pages = [st.Page(page, title=name, url_path=str(i or 'home'), default=i == 0) for i, name in enumerate(PAGES)]
st.navigation(pages, position="hidden")
st.session_state[PAGE_LINKS_KEY] = dict(zip(PAGES, pages))
render_page(TARGET)
"""


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")


def _dataset():
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(len(points))],
                        "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]}, dtype=str)
    return validate_and_clean(raw, "field_export.csv")


def _app(page, dataset=None, script=SCRIPT):
    at = AppTest.from_string(script.replace("PAGE", repr(page)) if script is SCRIPT else script.replace("TARGET", repr(page)),
                             default_timeout=120)
    if dataset is not None:
        at.session_state["dataset"] = dataset
    return at.run()


def _saved_run_with_reports():
    at = _app("Summary", _dataset())
    at.button(key="save_run").click().run()
    at.button(key="generate_reports").click().run()
    assert not at.exception


@pytest.mark.parametrize("name,label", [
    ("incident_id", "Incident ID"), ("affected_rows", "Affected Rows"), ("location_name", "Location Name"),
    ("severity", "Severity"), ("my extra_col", "My Extra Col"), (" id ", "ID"),
])
def test_column_label(name, label):
    assert column_label(name) == label


def test_history_column_lists_cover_every_column_exactly():
    run = {"created_at": "2026-10-31T10:20:30+00:00", "run_id": "abcdef0123456789", "source_name": "a.csv",
           "valid_rows": 1, "total_rows": 1, "report_paths": [], "cluster_count": 0, "candidate_hotspot_count": 0,
           "noise_count": 1, "config": dashboard.DEFAULT_ANALYSIS_CONFIG}
    assert set(HISTORY_RESULT_COLUMNS) | set(HISTORY_PARAMETER_COLUMNS) == set(_history_row(run))
    assert _run_label(run) == "2026-10-31 10:20 UTC · a.csv · abcdef01"


def test_empty_history_has_no_csv_warning():
    at = _app("History & Reports")
    assert not at.exception
    assert CSV_SAFETY_WARNING not in [w.value for w in at.warning]
    info = [i.value for i in at.info]
    assert any("No runs saved yet" in m for m in info) and any("Generate reports" in m for m in info)


def test_populated_history_shows_warning_tables_and_parameters():
    _saved_run_with_reports()
    at = _app("History & Reports")
    assert not at.exception
    assert CSV_SAFETY_WARNING in [w.value for w in at.warning]
    assert len(at.dataframe) == 2                                      # results, then parameters
    assert set(HISTORY_PARAMETER_COLUMNS) <= set(at.dataframe[1].value.columns)
    assert [e.label for e in at.main.expander] == ["Analysis parameters for each run"]
    assert TABLE_SCROLL_HINT in [c.value for c in at.caption]
    assert at.selectbox(key="history_report_run").value                # still the full run id


def test_links_render_when_pages_are_registered_and_are_skipped_otherwise():
    assert len(_app("Clusters (DBSCAN)").get("page_link")) == 0
    linked = _app("Clusters (DBSCAN)", script=LINKED_SCRIPT)
    assert not linked.exception
    assert [el.proto.label for el in linked.get("page_link")] == ["Go to Data"]
    history = _app("History & Reports", script=LINKED_SCRIPT)
    assert [el.proto.label for el in history.get("page_link")] == ["Go to Summary"]    # one link, not two


def test_app_registers_every_page_for_links():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert list(at.session_state[dashboard.PAGE_LINKS_KEY]) == list(dashboard.PAGES)


def test_empty_state_css_is_static_and_scoped():
    css = ui_theme.SHELL_CSS
    for prefix in (ui_theme.EMPTY_STATE_PREFIX, ui_theme.HISTORY_PANEL_PREFIX):
        assert f'[class*="st-key-{prefix}"]' in css
    assert ui_theme.ACCENT_HOVER in css and "<" not in css and "script" not in css.lower()
