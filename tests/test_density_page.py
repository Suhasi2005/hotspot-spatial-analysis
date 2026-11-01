"""Density page and dark heatmap tests (redesign Stage 4).

Display only: these confirm how the KDE result is drawn and explained. The KDE itself
is covered by tests/test_density_analysis.py. Synthetic data and temporary storage only.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from config.settings import DEFAULT_ANALYSIS_CONFIG
from modules import ui_theme
from modules.app_controller import estimate_density
from modules.dashboard import KDE_DISCLAIMER
from modules.data_validator import validate_and_clean
from modules.map_visualization import (
    DENSITY_COLORS,
    DENSITY_LEGEND,
    DENSITY_MAX_OPACITY,
    DENSITY_SMOOTHING_NOTE,
    DENSITY_TRANSPARENT_BELOW,
    THRESHOLD_CELL_CLASS,
    THRESHOLD_RGBA,
    _density_legend,
    build_density_map,
    density_overlay_rgba,
    density_rgba,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page('Density (KDE)')\n"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")


def _dataset():
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(len(points))],
                        "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]}, dtype=str)
    return validate_and_clean(raw, "synthetic_density.csv")


def _density():
    return estimate_density(_dataset(), DEFAULT_ANALYSIS_CONFIG)


def _app():
    at = AppTest.from_string(SCRIPT, default_timeout=120)
    at.session_state["dataset"] = _dataset()
    return at.run()


def _text(at):
    return " ".join(m.value for m in at.main.markdown)


# --- rendering ---------------------------------------------------------------------------------


def test_density_ramp_runs_from_dark_to_hot():
    assert len(DENSITY_COLORS) == 5
    low, high = density_rgba(np.array([0.05])), density_rgba(np.array([1.0]))
    assert tuple(high[0, :3]) == (0xF0, 0x45, 0x3A) and high[0, 3] == round(255 * DENSITY_MAX_OPACITY)
    assert low[0, 3] < high[0, 3] / 2                                    # low density stays dark


def test_weak_concentrations_leave_the_darkest_colour():
    weak = density_rgba(np.array([0.04]))
    assert weak[0, 2] > 0x90                                             # well into the blue part of the ramp
    assert weak[0, 3] > 80                                               # and visible on the dark basemap


def test_opacity_rises_steadily_with_the_score():
    alpha = density_rgba(np.linspace(0.0, 1.0, 21))[..., 3].astype(int)
    assert (np.diff(alpha) > 0).all()


def test_overlay_uses_the_shared_colours_and_hides_only_the_lowest_cells():
    density = _density()
    image = density_overlay_rgba(density)
    peak_alpha = image[..., 3].max()
    assert peak_alpha == round(255 * DENSITY_MAX_OPACITY)
    assert ((density.density / density.density.max() < DENSITY_TRANSPARENT_BELOW)[::-1] == (image[..., 3] == 0)).mean() > 0.99


def test_rendering_never_changes_the_kde_result():
    density = _density()
    values, lat, lon, threshold = density.density.copy(), density.grid_lat.copy(), density.grid_lon.copy(), density.high_density_threshold
    density_overlay_rgba(density)
    density_overlay_rgba(density, threshold_mask=True)
    build_density_map(density).get_root().render()
    assert np.array_equal(density.density, values) and np.array_equal(density.grid_lat, lat) and np.array_equal(density.grid_lon, lon)
    assert density.high_density_threshold == threshold


def test_threshold_layer_keeps_exact_cells_and_stands_apart_from_the_ramp():
    density = _density()
    mask = density_overlay_rgba(density, threshold_mask=True)
    assert ((mask[..., 3] > 0) == (density.density >= density.high_density_threshold)[::-1]).mean() > 0.99
    assert THRESHOLD_RGBA[:3] == (234, 242, 250)
    html = build_density_map(density).get_root().render()
    assert THRESHOLD_CELL_CLASS in html


def test_map_uses_the_dark_treatment_and_is_smoothed_only_on_the_kde_layer():
    fmap = build_density_map(_density())
    names = [type(c).__name__ for c in fmap._children.values()]
    assert "DarkMapStyle" in names and "MapLegend" in names and "LinearColormap" not in names
    overlays = [c for c in fmap._children.values() if type(c).__name__ == "ImageOverlay"]
    assert [o.pixelated for o in overlays] == [False, False]             # Folium's page-wide pixelated style is off
    html = fmap.get_root().render()
    assert ".leaflet-image-layer {" not in html
    assert f".{THRESHOLD_CELL_CLASS} {{ image-rendering: pixelated; }}" in html


# --- legend ------------------------------------------------------------------------------------


def test_legend_gradient_comes_from_the_map_colours():
    legend = _density_legend()
    for r, g, b, a in density_rgba(np.array([0.0, 0.5, 1.0])):
        assert f"rgba({r}, {g}, {b}, {a / 255:.3f})" in legend


def test_legend_explains_the_scale_honestly():
    legend = _density_legend()
    for word in ("Low", "Medium", "High", "Relative density score", "not incident counts", DENSITY_SMOOTHING_NOTE):
        assert word in legend
    assert "not incident counts or incidents/km²" in DENSITY_LEGEND
    assert legend.count("Relative density score") == 1


def test_initial_view_leaves_room_for_the_legend():
    fit = next(c for c in build_density_map(_density())._children.values() if type(c).__name__ == "FitBounds")
    assert fit.options["paddingTopLeft"][1] >= 140


# --- the page ----------------------------------------------------------------------------------


def test_kpis_use_only_existing_values():
    at = _app()
    assert not at.exception
    density = at.session_state[dashboard.CACHE_KEY]["density"]
    metrics = {m.label: m.value for m in at.metric}
    assert list(metrics) == ["Incidents used", "Grid cells", "Bandwidth", "Analysis status", "Peak relative score"]
    assert metrics["Peak relative score"] == f"{density.density.max():.4g}"
    assert metrics["Bandwidth"] == "300 m" and metrics["Incidents used"] == "19"


def test_panel_explains_density_and_how_it_differs_from_clusters():
    at = _app()
    text = _text(at)
    assert KDE_DISCLAIMER in [i.value for i in at.info]
    assert "where incidents concentrate" in text and "A hot area here is not automatically a cluster." in text
    assert "not statistically significant risk" in text
    assert "statistically significant hot" not in text


def test_smoothing_is_stated_on_the_page():
    assert any(DENSITY_SMOOTHING_NOTE in c.value for c in _app().caption)


def test_parameters_start_open_here_and_closed_elsewhere():
    at = _app()
    assert next(e for e in at.sidebar.expander if e.label == "Analysis parameters").proto.expanded is True
    other = AppTest.from_string(SCRIPT.replace("Density (KDE)", "Clusters (DBSCAN)"), default_timeout=120)
    other.session_state["dataset"] = _dataset()
    other.run()
    assert next(e for e in other.sidebar.expander if e.label == "Analysis parameters").proto.expanded is False


def test_bandwidth_control_updates_the_page():
    at = _app()
    at.number_input(key="p_bandwidth_m").set_value(600.0).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Bandwidth"] == "600 m"
    assert any("Bandwidth 600 m" in c.value for c in at.caption)


def test_kde_failure_is_still_reported():
    at = _app()
    at.number_input(key="p_grid_cell_m").set_value(1.0).run()
    assert not at.exception and any("KDE did not run" in e.value for e in at.error)
    assert any("side menu" in c.value for c in at.caption)               # phones need the way back to the controls


def test_density_kpi_css_is_scoped():
    assert f".st-key-{ui_theme.DENSITY_KPI_KEY} > *" in ui_theme.SHELL_CSS
