"""Regression tests for the application-wide fixes (redesign Stage 7).

Display and messaging only. Synthetic data and temporary storage only.
"""

import logging
import sqlite3
import tomllib
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from modules import ui_theme
from modules.contracts import AnalysisError
from modules.dashboard import failure_reason
from modules.data_validator import validate_and_clean
from modules.map_theme import MAP_BORDER
from modules.map_visualization import POINT_STYLE, build_incident_map, incident_marker_records

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
SCRIPT = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from modules.dashboard import render_page
render_page(st.session_state["page"])
"""
SECRET_PATH = r"D:\private\folder\reports"


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")
    return tmp_path


def _dataset(name="field_export.csv"):
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(len(points))],
                        "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]}, dtype=str)
    return validate_and_clean(raw, name)


def _session(page="Summary"):
    at = AppTest.from_string(SCRIPT, default_timeout=120)
    at.session_state["page"] = page
    at.session_state["dataset"] = _dataset()
    return at.run()


def _contrast(first, second):
    def luminance(colour):
        channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# --- control contrast ---------------------------------------------------------------------------------


@pytest.mark.parametrize("surface", [ui_theme.SURFACE, ui_theme.SURFACE_ELEVATED, ui_theme.BACKGROUND,
                                     ui_theme.SECONDARY_BACKGROUND, ui_theme.SIDEBAR_BACKGROUND])
def test_control_borders_reach_3_to_1_on_every_surface(surface):
    assert _contrast(ui_theme.BORDER_STRONG, surface) >= 3


def test_control_border_is_applied_everywhere():
    assert CONFIG["theme"]["borderColor"] == CONFIG["theme"]["sidebar"]["borderColor"] == ui_theme.BORDER_STRONG
    assert MAP_BORDER == ui_theme.BORDER_STRONG


def test_borders_stay_restrained():
    assert _contrast(ui_theme.BORDER_STRONG, ui_theme.SURFACE) < 4                # visible, not glaring
    assert _contrast(ui_theme.BORDER, ui_theme.SURFACE) < 2                       # card edges stay quiet
    assert CONFIG["theme"]["dataframeBorderColor"] == ui_theme.BORDER
    assert f".st-key-{ui_theme.SIDEBAR_RULE_KEY} hr {{ border-color: {ui_theme.BORDER}; }}" in ui_theme.SHELL_CSS


# --- one visual language --------------------------------------------------------------------------------


def test_there_is_one_kpi_card_style():
    css = ui_theme.SHELL_CSS
    assert [line for line in css.splitlines() if "min-height" in line and "st-key-kpi_" in line] ==         [next(line for line in css.splitlines() if line.startswith('[class*="st-key-kpi_"] {'))]
    assert not any(key in line and "padding" in line for line in css.splitlines()
                   for key in (ui_theme.SUMMARY_KPI_KEY, ui_theme.DENSITY_KPI_KEY, ui_theme.HISTORY_KPI_KEY))
    sizes = [line for line in css.splitlines() if "stMetricValue" in line and "font-size" in line and "badge" not in line]
    assert len(sizes) == 1 and f"font-size: {ui_theme.METRIC_VALUE_PX}px" in sizes[0]
    assert CONFIG["theme"]["metricValueFontSize"] == f"{ui_theme.METRIC_VALUE_PX}px"


def test_card_titles_use_one_heading_level():
    source = "\n".join((ROOT / "modules" / name).read_text(encoding="utf-8") for name in ("dashboard.py", "ui_components.py"))
    assert '"#### ' not in source and 'f"#### ' not in source


# --- Data page map -------------------------------------------------------------------------------------


def test_data_map_uses_the_dark_treatment():
    names = [type(c).__name__ for c in build_incident_map(_dataset())._children.values()]
    assert "DarkMapStyle" in names and "MapLegend" in names


def test_data_map_keeps_every_incident_and_its_position():
    dataset = _dataset()
    fmap = build_incident_map(dataset)
    layer = next(c for c in fmap._children.values() if type(c).__name__ == "FeatureGroup")
    markers = [c for c in layer._children.values() if type(c).__name__ == "CircleMarker"]
    records = incident_marker_records(dataset)
    assert [m.location for m in markers] == [[r["lat"], r["lon"]] for r in records]
    assert len(markers) == len(dataset.frame)
    assert all(m.options["fillColor"] == POINT_STYLE["fill_color"] for m in markers)


def test_data_map_legend_counts_what_is_drawn():
    legend = next(c for c in build_incident_map(_dataset(), max_points=5)._children.values()
                  if type(c).__name__ == "MapLegend")
    assert "Incidents: 5 shown" in legend.body and POINT_STYLE["fill_color"] in legend.body


def test_data_map_points_stand_out_on_the_dark_basemap():
    assert _contrast(POINT_STYLE["fill_color"], ui_theme.BACKGROUND) >= 3


def test_data_map_view_leaves_room_for_the_legend():
    fit = next(c for c in build_incident_map(_dataset())._children.values() if type(c).__name__ == "FitBounds")
    assert fit.options["paddingTopLeft"][1] >= 60


# --- error messages -------------------------------------------------------------------------------------


@pytest.mark.parametrize("exc, expected", [
    (OSError(2, "No such file or directory", SECRET_PATH), "a file or folder could not be read or written"),
    (FileNotFoundError(2, "No such file", SECRET_PATH), "a file or folder could not be read or written"),
    (FileExistsError(183, "Cannot create a file", SECRET_PATH), "a file or folder could not be read or written"),
    (PermissionError(13, "Permission denied", SECRET_PATH), "the app does not have permission to use the storage folder"),
    (sqlite3.OperationalError(f"unable to open database file {SECRET_PATH}"), "the history database could not be used"),
    (ValueError(f"bad value in {SECRET_PATH}"), "a saved record could not be used"),
    (LookupError(f"no row in {SECRET_PATH}"), "a saved record could not be used"),
])
def test_failure_reason_never_repeats_system_details(exc, expected):
    reason = failure_reason(exc)
    assert reason == expected and "private" not in reason and "\\" not in reason


def test_failure_reason_keeps_messages_written_for_users():
    assert failure_reason(AnalysisError("Reports are only generated for usable datasets.")) == \
        "Reports are only generated for usable datasets"
    assert failure_reason(FileExistsError("Reports folder 'abc' already exists; reports are generated once per run.")) == \
        "Reports folder 'abc' already exists; reports are generated once per run"
    assert failure_reason(OSError("Generated report.pdf is not a complete PDF.")) == "Generated report.pdf is not a complete PDF"


def test_report_failure_hides_the_path_but_logs_it(storage, monkeypatch, caplog):
    blocker = storage / "a_file_not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", blocker)
    at = _session()
    at.button(key="save_run").click().run()
    with caplog.at_level(logging.ERROR, logger="modules.dashboard"):
        at.button(key="generate_reports").click().run()
    assert not at.exception
    shown = " ".join(e.value for e in at.error)
    assert shown.startswith("Could not generate reports:") and "application log" in shown
    assert str(storage) not in shown and blocker.name not in shown
    assert "Could not generate reports" in caplog.text and blocker.name in caplog.text    # the detail survives


def test_save_failure_hides_the_path_but_logs_it(monkeypatch, caplog):
    def failing(*args, **kwargs):
        raise OSError(28, "No space left on device", SECRET_PATH)
    monkeypatch.setattr(dashboard, "record_run", failing)
    at = _session()
    with caplog.at_level(logging.ERROR, logger="modules.dashboard"):
        at.button(key="save_run").click().run()
    shown = " ".join(e.value for e in at.error)
    assert "Could not save the run" in shown and "private" not in shown and "private" in caplog.text


def test_unreadable_history_hides_the_path(monkeypatch, storage):
    folder = storage / "a_folder"
    folder.mkdir()
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", folder)
    at = _session("History & Reports")
    shown = " ".join(e.value for e in at.error)
    assert "Could not read the run history" in shown and str(storage) not in shown


def test_unexpected_errors_show_no_traceback_to_users():
    assert CONFIG["client"]["showErrorDetails"] == "none"


# --- parameters survive navigation -----------------------------------------------------------------------


def test_defaults_are_unchanged_when_nothing_was_touched():
    at = _session()
    values = {key: at.number_input(key=key).value for key in ("p_eps_m", "p_min_samples", "p_min_incidents",
                                                              "p_bandwidth_m", "p_grid_cell_m", "p_quantile")}
    assert values == {"p_eps_m": 250.0, "p_min_samples": 5, "p_min_incidents": 10,
                      "p_bandwidth_m": 300.0, "p_grid_cell_m": 100.0, "p_quantile": 0.95}
    assert not at.warning                                                # no duplicate-default warning from Streamlit


def _go(at, page):
    at.session_state["page"] = page
    return at.run()


def test_parameters_survive_pages_without_the_parameter_panel():
    at = _session("Clusters (DBSCAN)")
    at.number_input(key="p_eps_m").set_value(35.0).run()
    at.number_input(key="p_bandwidth_m").set_value(600.0).run()
    _go(at, "History & Reports")                                         # no parameter widgets on this page
    _go(at, "Summary")
    assert at.number_input(key="p_eps_m").value == 35.0 and at.number_input(key="p_bandwidth_m").value == 600.0
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Bandwidth"] == "600 m"
    assert at.session_state[dashboard.CACHE_KEY]["config"].dbscan.eps_m == 35.0


def test_the_saved_run_uses_the_parameters_on_screen_after_navigating(storage):
    at = _session("Clusters (DBSCAN)")
    at.number_input(key="p_bandwidth_m").set_value(600.0).run()
    _go(at, "Data")
    _go(at, "Summary")
    at.button(key="save_run").click().run()
    run = dashboard.list_runs(db_path=dashboard.HISTORY_DB_PATH)[0]
    assert run["config"].kde.bandwidth_m == 600.0


def test_saved_state_survives_navigation_when_parameters_are_kept():
    at = _session("Clusters (DBSCAN)")
    at.number_input(key="p_eps_m").set_value(35.0).run()
    _go(at, "Summary")
    at.button(key="save_run").click().run()
    saved = at.session_state[dashboard.CACHE_KEY]["saved_run_id"]
    _go(at, "History & Reports")
    _go(at, "Summary")
    assert at.session_state[dashboard.CACHE_KEY]["saved_run_id"] == saved    # the same analysis, not a re-run
    assert "save_run" not in [b.key for b in at.button]


# --- first screen on phones ------------------------------------------------------------------------------


def test_clusters_map_comes_before_its_captions():
    source = (ROOT / "modules" / "dashboard.py").read_text(encoding="utf-8")
    page = source[source.index("def _render_clusters_page"):source.index("def _render_cluster_panel")]
    assert page.index('key="cluster_map"') < page.index("are in the side menu") < page.index("under the current display filters")
