"""Clusters page and dark map tests (redesign Stage 3).

Display only: the mask and map tests confirm what is drawn, and the analysis itself
is covered by the DBSCAN tests. Synthetic data and temporary storage only.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from config.settings import DEFAULT_ANALYSIS_CONFIG
from modules import map_theme, map_visualization, ui_theme
from modules.app_controller import cluster_dataset
from modules.contracts import CLUSTER_LABEL_COLUMN, NOISE_LABEL
from modules.dashboard import cluster_rows_html, cluster_view, display_mask
from modules.data_validator import validate_and_clean
from modules.map_visualization import (
    CANDIDATE_OUTLINE_COLOR,
    CLUSTER_LABEL_LAYER,
    CLUSTER_PALETTE,
    NOISE_COLOR,
    NOISE_STYLE,
    build_cluster_map,
    build_incident_map,
    cluster_marker_records,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page('Clusters (DBSCAN)')\n"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")


def _dataset():
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    n = len(points)
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(n)],
                        "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points],
                        "severity": (["major", "minor"] * n)[:n]}, dtype=str)
    return validate_and_clean(raw, "synthetic_clusters.csv")


def _clusters():
    return cluster_dataset(_dataset(), DEFAULT_ANALYSIS_CONFIG)


def _app():
    at = AppTest.from_string(SCRIPT, default_timeout=120)
    at.session_state["dataset"] = _dataset()
    return at.run()


def _contrast(fg, bg):
    def luminance(colour):
        channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    light, dark = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _layer_names(fmap):
    return [c.layer_name for c in fmap._children.values() if type(c).__name__ == "FeatureGroup"]


# --- dark map ----------------------------------------------------------------------------------


def test_map_theme_colours_agree_with_the_design_system():
    pairs = {"MAP_BACKGROUND": "BACKGROUND", "MAP_PANEL": "SURFACE", "MAP_BORDER": "BORDER_STRONG",
             "MAP_TEXT": "TEXT_PRIMARY", "MAP_TEXT_MUTED": "TEXT_SECONDARY", "MAP_ACCENT": "ACCENT"}
    for ours, theirs in pairs.items():
        assert getattr(map_theme, ours) == getattr(ui_theme, theirs)


def test_dark_basemap_filters_only_the_tile_pane_and_needs_no_key():
    css = map_theme.DARK_MAP_CSS
    assert f".leaflet-tile-pane {{ filter: {map_theme.TILE_FILTER}; }}" in css
    assert "overlay-pane" not in css and "marker-pane" not in css
    html = build_cluster_map(_clusters()).get_root().render()
    assert "tile.openstreetmap.org" in html and "cartocdn" not in html and "apikey" not in html.lower()
    assert "OpenStreetMap" in html                                       # attribution kept


def test_cluster_map_has_the_style_legend_and_layers():
    fmap = build_cluster_map(_clusters())
    names = [type(c).__name__ for c in fmap._children.values()]
    assert "DarkMapStyle" in names and "MapLegend" in names and "LayerControl" in names
    assert _layer_names(fmap) == ["Cluster extents (centroid + radius_m)", "Incidents (cluster colour; grey = noise)",
                                  CLUSTER_LABEL_LAYER]


def test_other_maps_are_not_changed_in_this_stage():
    names = [type(c).__name__ for c in build_incident_map(_dataset())._children.values()]
    assert "DarkMapStyle" not in names and "MapLegend" not in names


def test_marks_stay_visible_on_the_dark_map():
    assert _contrast(NOISE_COLOR, map_theme.MAP_BACKGROUND) >= 3 and _contrast(CANDIDATE_OUTLINE_COLOR, map_theme.MAP_BACKGROUND) >= 3
    assert all(_contrast(colour, map_theme.MAP_BACKGROUND) >= 3 for colour in CLUSTER_PALETTE)
    assert NOISE_STYLE["color"] == NOISE_COLOR == NOISE_STYLE["fill_color"]   # the style follows the constant


def test_map_coordinates_and_labels_are_exactly_the_dbscan_output():
    result = _clusters()
    records = cluster_marker_records(result, max_points=None)
    assert [r["lat"] for r in records] == result.labeled_frame["latitude"].tolist()
    assert [r["lon"] for r in records] == result.labeled_frame["longitude"].tolist()
    assert [r["cluster_label"] for r in records] == result.labeled_frame[CLUSTER_LABEL_COLUMN].tolist()


def test_chips_and_legend_show_real_counts_for_what_is_drawn():
    result = _clusters()
    html = build_cluster_map(result).get_root().render().replace(chr(92) + "u00b7", "·")   # scripts escape it
    first = result.clusters[0]
    assert f"Cluster {first.cluster_label} · {first.incident_count}" in html
    assert f"Cluster {first.cluster_label}: {first.incident_count} shown" in html
    assert "Noise: 1 shown" in html and "Candidate hotspot (size rule)" in html


def test_legend_follows_the_filters():
    result = _clusters()
    labels = result.labeled_frame[CLUSTER_LABEL_COLUMN].to_numpy()
    html = build_cluster_map(result, point_mask=labels != NOISE_LABEL).get_root().render()
    assert "Noise:" not in html
    other = next(c for c in result.clusters if not c.is_candidate_hotspot)
    html = build_cluster_map(result, point_mask=labels == other.cluster_label, cluster_labels={other.cluster_label}).get_root().render()
    assert "Candidate hotspot (size rule)" not in html and f"Cluster {other.cluster_label}: {other.incident_count} shown" in html


def test_initial_view_keeps_incidents_clear_of_the_legend():
    fit = next(c for c in build_cluster_map(_clusters())._children.values() if type(c).__name__ == "FitBounds")
    left, top = fit.options["paddingTopLeft"]
    assert left == 20
    # title, two clusters, noise and the candidate row
    assert top == map_visualization.LEGEND_FRAME_PX + 5 * map_visualization.LEGEND_ROW_PX


def test_legend_steps_aside_for_popups():
    html = build_cluster_map(_clusters()).get_root().render()
    assert 'map.on("popupopen"' in html and 'map.on("popupclose"' in html


def test_legend_stays_small_with_many_clusters():
    class Summary:
        def __init__(self, label):
            self.cluster_label, self.is_candidate_hotspot = label, False
    legend = map_visualization._cluster_legend([], [Summary(i) for i in range(12)])
    assert "+ 4 more clusters" in legend and "Cluster 8" not in legend


# --- what is displayed --------------------------------------------------------------------------


def test_cluster_view_with_everything_chosen_matches_the_existing_mask():
    frame = _clusters().labeled_frame
    mask, visible = cluster_view(frame, None, None, True, {0, 1}, {0}, False)
    assert visible is None and np.array_equal(mask, display_mask(frame))


def test_choosing_one_cluster_keeps_noise_on_its_own_switch():
    frame = _clusters().labeled_frame
    labels = frame[CLUSTER_LABEL_COLUMN].to_numpy()
    mask, visible = cluster_view(frame, None, None, True, {1}, {0}, False)
    assert visible == {1} and np.array_equal(mask, (labels == 1) | (labels == NOISE_LABEL))
    mask, _ = cluster_view(frame, None, None, False, {1}, {0}, False)
    assert np.array_equal(mask, labels == 1)


def test_candidates_only_keeps_its_meaning():
    frame = _clusters().labeled_frame
    labels = frame[CLUSTER_LABEL_COLUMN].to_numpy()
    mask, visible = cluster_view(frame, None, None, True, {0, 1}, {0}, True)
    assert visible == {0} and np.array_equal(mask, labels == 0)
    mask, visible = cluster_view(frame, None, None, True, {1}, {0}, True)
    assert visible == set() and not mask.any()


def test_cluster_view_does_not_change_the_frame():
    frame = _clusters().labeled_frame
    before = frame.copy(deep=True)
    cluster_view(frame, {"major"}, None, False, {1}, {0}, False)
    pd.testing.assert_frame_equal(frame, before)


def test_panel_rows_show_real_cluster_facts():
    result = _clusters()
    rows = cluster_rows_html(result)
    for c in result.clusters:
        assert f"<b>Cluster {c.cluster_label}</b>" in rows and f"{c.incident_count:,} incidents" in rows
    assert rows.count("Candidate hotspot") == 1


# --- the page ---------------------------------------------------------------------------------


def test_selecting_a_cluster_changes_the_display_not_the_results():
    at = _app()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    selector = at.get("button_group")[0]
    assert selector.value == [0, 1] or selector.proto.default
    at.session_state["f_clusters_2"] = [1]
    at.run()
    assert not at.exception and {m.label: m.value for m in at.metric} == metrics
    assert any("Showing 7 of 19" in c.value for c in at.caption)         # 6 members + 1 noise point


def test_kpis_and_tabs_are_unchanged():
    at = _app()
    assert {m.label: m.value for m in at.metric} == {"Clusters": "2", "Candidate hotspots": "1",
                                                     "Noise incidents": "1 of 19", "Noise share": "5.3%"}
    assert [t.label for t in at.tabs] == ["Table", "Cluster sizes"]


def test_method_notes_are_kept_in_the_panel():
    at = _app()
    assert "How to read this map" in [e.label for e in at.main.expander]
    text = " ".join(m.value for m in at.main.markdown)
    assert "Thick white outline" in text and "does not test statistical significance" in text


def test_no_clusters_is_explained():
    at = AppTest.from_string(SCRIPT, default_timeout=120)
    at.session_state["dataset"] = _dataset()
    at.run()
    at.number_input(key="p_min_samples").set_value(50).run()
    assert not at.exception
    assert any("no clusters" in i.value for i in at.info)
    assert any("No clusters with these parameters." in c.value for c in at.caption)


def test_mobile_hint_is_hidden_on_wide_screens():
    assert f".st-key-{ui_theme.MOBILE_ONLY_KEY} {{ display: none; }}" in ui_theme.SHELL_CSS
