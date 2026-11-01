"""Incident-map tests. Synthetic data only; no tile server is contacted."""

import folium
import pandas as pd
import pytest

from modules.contracts import AnalysisError
from modules.data_validator import validate_and_clean
from modules.map_visualization import build_incident_map, incident_marker_records


def _dataset(rows, columns=("incident_id", "latitude", "longitude"), index=None):
    raw = pd.DataFrame([[str(v) for v in r] for r in rows], columns=list(columns), dtype=str)
    if index is not None:
        raw.index = index
    return validate_and_clean(raw, "synthetic")


def _markers(fmap: folium.Map) -> list[folium.CircleMarker]:
    found = []

    def walk(element):
        for child in element._children.values():
            if isinstance(child, folium.CircleMarker):
                found.append(child)
            walk(child)

    walk(fmap)
    return found


def _tooltip_text(marker: folium.CircleMarker) -> str:
    return next(c.text for c in marker._children.values() if isinstance(c, folium.Tooltip))


def _has_fit_bounds(fmap: folium.Map) -> bool:
    return any(type(c).__name__ == "FitBounds" for c in fmap._children.values())


def test_single_incident_is_centred_without_fit_bounds():
    fmap = build_incident_map(_dataset([["A1", "23.0225", "72.5714"]]))
    markers = _markers(fmap)
    assert len(markers) == 1
    assert markers[0].location == [23.0225, 72.5714]
    assert fmap.location == [23.0225, 72.5714]
    assert not _has_fit_bounds(fmap)


def test_multiple_incidents_fit_their_bounding_box():
    rows = [["A", "23.00", "72.50"], ["B", "23.10", "72.60"], ["C", "23.05", "72.70"]]
    fmap = build_incident_map(_dataset(rows))
    assert [m.location for m in _markers(fmap)] == [[23.0, 72.5], [23.1, 72.6], [23.05, 72.7]]
    assert fmap.location == pytest.approx([23.05, 72.60])           # bbox midpoint, from data
    assert _has_fit_bounds(fmap)


def test_markers_match_input_coordinates_and_ids():
    rows = [["X-1", "-33.8688", "151.2093"], ["X-2", "51.5074", "-0.1278"]]
    dataset = _dataset(rows)
    fmap = build_incident_map(dataset)
    markers = _markers(fmap)
    assert [m.location for m in markers] == dataset.frame[["latitude", "longitude"]].values.tolist()
    assert [_tooltip_text(m) for m in markers] == ["X-1", "X-2"]
    assert [r["incident_id"] for r in incident_marker_records(dataset)] == ["X-1", "X-2"]


def test_non_consecutive_source_index_is_read_by_position():
    rows = [["A", "10", "20"], ["B", "bad", "21"], ["C", "12", "22"], ["D", "13", "23"]]
    dataset = _dataset(rows, index=[40, 7, 15, 3])                  # B rejected -> labels 40, 15, 3
    assert list(dataset.frame.index) == [40, 15, 3]
    records = incident_marker_records(dataset)
    assert [(r["incident_id"], r["lat"], r["lon"], r["source_row"]) for r in records] == [
        ("A", 10.0, 20.0, 40), ("C", 12.0, 22.0, 15), ("D", 13.0, 23.0, 3),
    ]
    assert [m.location for m in _markers(build_incident_map(dataset))] == [[10.0, 20.0], [12.0, 22.0], [13.0, 23.0]]


def test_missing_optional_columns_give_minimal_popup():
    record = incident_marker_records(_dataset([["A", "1.5", "2.5"]]))[0]
    assert record["popup_html"] == "<b>Incident</b>: A<br><b>Lat, Lon</b>: 1.500000, 2.500000"


def test_optional_columns_appear_when_present_and_blanks_are_skipped():
    cols = ("incident_id", "latitude", "longitude", "incident_date", "severity", "location_name", "incident_type")
    rows = [["A", "1", "2", "2024-03-05", "major", "Ring Road", ""],
            ["B", "1", "2", "", "", "", "collision"]]
    a, b = incident_marker_records(_dataset(rows, columns=cols))
    assert "<b>Date</b>: 2024-03-05" in a["popup_html"]
    assert "<b>Severity</b>: major" in a["popup_html"]
    assert "<b>Location</b>: Ring Road" in a["popup_html"]
    assert "Type" not in a["popup_html"]
    assert "<b>Type</b>: collision" in b["popup_html"]
    assert "Date" not in b["popup_html"] and "Severity" not in b["popup_html"]


def test_user_values_are_html_escaped():
    cols = ("incident_id", "latitude", "longitude", "location_name")
    payload_id = "<script>alert('id')</script>"
    payload_loc = '<img src=x onerror="alert(1)"> & Co'
    dataset = _dataset([[payload_id, "1", "2", payload_loc]], columns=cols)
    record = incident_marker_records(dataset)[0]
    assert record["incident_id"] == payload_id                      # data itself unchanged
    assert "<script>" not in record["popup_html"] and "<img" not in record["popup_html"]
    assert "&lt;script&gt;" in record["popup_html"]
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; Co" in record["popup_html"]
    assert record["tooltip"] == "&lt;script&gt;alert(&#x27;id&#x27;)&lt;/script&gt;"
    rendered = build_incident_map(dataset).get_root().render()
    assert payload_id not in rendered and "<img src=x" not in rendered


def test_empty_dataset_raises_analysis_error():
    with pytest.raises(AnalysisError, match="No valid incidents"):
        build_incident_map(_dataset([]))


def test_unusable_dataset_raises_analysis_error():
    dataset = _dataset([["", "1", "2"], ["B", "x", "2"]])
    assert dataset.report.is_usable is False
    with pytest.raises(AnalysisError):
        build_incident_map(dataset)
    with pytest.raises(AnalysisError):
        incident_marker_records(dataset)


def test_input_frame_is_not_mutated():
    cols = ("incident_id", "latitude", "longitude", "incident_date")
    dataset = _dataset([["A", "1", "2", "2024-01-01"], ["B", "3", "4", ""]], columns=cols)
    dataset.frame.index = [5, 9]
    before = dataset.frame.copy(deep=True)
    build_incident_map(dataset)
    incident_marker_records(dataset)
    pd.testing.assert_frame_equal(dataset.frame, before)


def test_output_is_deterministic_for_fixed_input():
    dataset = _dataset([["A", "1", "2"], ["B", "3", "4"], ["C", "5", "6"]])
    assert incident_marker_records(dataset) == incident_marker_records(dataset)
    first, second = build_incident_map(dataset), build_incident_map(dataset)
    assert [m.location for m in _markers(first)] == [m.location for m in _markers(second)]
    assert first.location == second.location


def test_max_points_caps_markers_in_file_order():
    dataset = _dataset([[f"I{i}", "1", str(i)] for i in range(10)])
    assert [r["incident_id"] for r in incident_marker_records(dataset, max_points=3)] == ["I0", "I1", "I2"]
    assert len(_markers(build_incident_map(dataset, max_points=3))) == 3
    assert len(_markers(build_incident_map(dataset, max_points=None))) == 10


# =====================================================================================
# Stage 7: cluster map and density map
# =====================================================================================

import copy  # noqa: E402
import json  # noqa: E402
import html as html_module  # noqa: E402

import numpy as np  # noqa: E402

from config.settings import CandidateHotspotCriteria, DBSCANParams, KDEParams  # noqa: E402
from modules.contracts import CLUSTER_LABEL_COLUMN, ClusterResult, ClusterSummary, DensityResult  # noqa: E402
from modules.dbscan_analysis import run_dbscan  # noqa: E402
from modules.density_analysis import run_kde  # noqa: E402
from modules.map_visualization import (  # noqa: E402
    CANDIDATE_OUTLINE_COLOR,
    CANDIDATE_TOOLTIP,
    CLUSTER_PALETTE,
    DENSITY_LEGEND,
    NOISE_COLOR,
    THRESHOLD_LAYER_NAME,
    THRESHOLD_RGBA,
    build_cluster_map,
    build_density_map,
    cluster_color,
    cluster_marker_records,
    density_overlay_bounds,
    density_overlay_rgba,
)


def _circles(fmap: folium.Map) -> list[folium.Circle]:
    found = []

    def walk(element):
        for child in element._children.values():
            if isinstance(child, folium.Circle):
                found.append(child)
            walk(child)

    walk(fmap)
    return found


def _two_cluster_result(index=None, ids=None):
    """Real DBSCAN on 6 + 12 tight points plus 2 noise points (labels deterministic)."""
    group_a = [(23.0200 + 0.0001 * i, 72.5700) for i in range(6)]
    group_b = [(23.0650 + 0.0001 * i, 72.5800) for i in range(12)]
    noise = [(23.1000, 72.6500), (22.9500, 72.4500)]
    points = group_a + group_b + noise
    ids = ids or [f"P{i}" for i in range(len(points))]
    dataset = _dataset([[ids[i], p[0], p[1]] for i, p in enumerate(points)], index=index)
    return run_dbscan(dataset, DBSCANParams(eps_m=250, min_samples=5), CandidateHotspotCriteria(min_incidents=10))


# --- cluster map -------------------------------------------------------------------


def test_cluster_colours_are_stable_distinct_and_noise_is_grey():
    assert len(set(CLUSTER_PALETTE)) == 10 and NOISE_COLOR not in CLUSTER_PALETTE
    assert [cluster_color(i) for i in range(10)] == list(CLUSTER_PALETTE)
    assert cluster_color(3) == cluster_color(3) and cluster_color(-1) == NOISE_COLOR


def test_points_are_coloured_by_label_and_noise_is_grey_and_smaller():
    result = _two_cluster_result()
    labels = result.labeled_frame[CLUSTER_LABEL_COLUMN].tolist()
    markers = _markers(build_cluster_map(result))
    assert len(markers) == 20
    for marker, label in zip(markers, labels):
        expected = NOISE_COLOR if label == -1 else cluster_color(label)
        assert marker.options["color"] == expected and marker.options["fillColor"] == expected
    noise_radii = {m.options["radius"] for m, lab in zip(markers, labels) if lab == -1}
    member_radii = {m.options["radius"] for m, lab in zip(markers, labels) if lab != -1}
    assert max(noise_radii) < min(member_radii)


def test_every_cluster_gets_a_circle_at_its_reported_centroid_and_radius():
    result = _two_cluster_result()
    circles = _circles(build_cluster_map(result))
    assert len(circles) == len(result.clusters) == 2
    for circle, summary in zip(circles, result.clusters):
        assert circle.location == [summary.centroid_lat, summary.centroid_lon]
        assert circle.options["radius"] == summary.radius_m


def test_candidate_hotspots_are_outlined_with_an_honest_tooltip():
    result = _two_cluster_result()
    by_label = {c.cluster_label: c for c in result.clusters}
    for circle in _circles(build_cluster_map(result)):
        text = next(ch.text for ch in circle._children.values() if isinstance(ch, folium.Tooltip))
        label = int(text.split()[1].rstrip(":"))
        if by_label[label].is_candidate_hotspot:
            assert circle.options["color"] == CANDIDATE_OUTLINE_COLOR and circle.options["weight"] == 4
            assert "Candidate hotspot — size rule only" in text
        else:
            assert circle.options["weight"] == 1 and "Candidate" not in text
        assert "significan" not in text.replace("not statistical significance", "")
    assert "not statistical significance" in CANDIDATE_TOOLTIP
    assert sum(c.is_candidate_hotspot for c in result.clusters) == 1     # the 12-point group only


def test_point_cap_limits_markers_but_keeps_every_cluster_circle():
    result = _two_cluster_result()
    fmap = build_cluster_map(result, max_points=3)
    assert len(_markers(fmap)) == 3 and len(_circles(fmap)) == 2
    assert [r["incident_id"] for r in cluster_marker_records(result, max_points=3)] == ["P0", "P1", "P2"]


def test_display_mask_and_cluster_subset_affect_only_what_is_drawn():
    result = _two_cluster_result()
    labels = result.labeled_frame[CLUSTER_LABEL_COLUMN].to_numpy()
    mask = labels != -1                                                  # hide noise
    fmap = build_cluster_map(result, point_mask=mask, cluster_labels={labels[6]})
    assert len(_markers(fmap)) == 18 and len(_circles(fmap)) == 1
    with pytest.raises(AnalysisError, match="point_mask"):
        build_cluster_map(result, point_mask=np.ones(3, dtype=bool))
    with pytest.raises(AnalysisError, match="point_mask"):
        build_cluster_map(result, point_mask=np.ones(20))                # not boolean


def test_cluster_map_reads_by_position_with_non_consecutive_index():
    index = [900, 3, 57, 12, 8, 41, 2, 77, 64, 30, 5, 18, 99, 6, 7, 44, 21, 10, 1000, 4]
    result = _two_cluster_result(index=index)
    records = cluster_marker_records(result, max_points=None)
    assert [r["source_row"] for r in records] == index
    assert [r["lat"] for r in records] == result.labeled_frame["latitude"].tolist()
    assert [r["cluster_label"] for r in records] == result.labeled_frame[CLUSTER_LABEL_COLUMN].tolist()


def test_cluster_popups_are_escaped():
    ids = [f"P{i}" for i in range(20)]
    ids[0] = "<script>alert('x')</script>"
    result = _two_cluster_result(ids=ids)
    record = cluster_marker_records(result)[0]
    assert "<script>" not in record["popup_html"] and "&lt;script&gt;" in record["popup_html"]
    assert "<b>DBSCAN</b>: cluster" in record["popup_html"]
    assert ids[0] not in build_cluster_map(result).get_root().render()


def test_invalid_or_empty_cluster_results_fail_clearly():
    result = _two_cluster_result()
    bad = copy.deepcopy(result)
    bad.noise_count += 1
    with pytest.raises(AnalysisError, match="noise_count"):
        build_cluster_map(bad)
    empty = ClusterResult(labeled_frame=result.labeled_frame.iloc[:0], clusters=[], noise_count=0, params={})
    with pytest.raises(AnalysisError, match="empty"):
        build_cluster_map(empty)


def test_cluster_map_does_not_mutate_and_is_deterministic():
    result = _two_cluster_result()
    frame_before = result.labeled_frame.copy(deep=True)
    summaries_before = copy.deepcopy(result.clusters)
    first, second = build_cluster_map(result), build_cluster_map(result)
    pd.testing.assert_frame_equal(result.labeled_frame, frame_before)
    assert result.clusters == summaries_before
    assert [m.location for m in _markers(first)] == [m.location for m in _markers(second)]
    assert [m.options for m in _markers(first)] == [m.options for m in _markers(second)]
    assert cluster_marker_records(result) == cluster_marker_records(result)


# --- density map -------------------------------------------------------------------------


def _density(grid_lat, grid_lon, values, threshold, n_points=1, extra_params=None):
    params = {"n_points": n_points, "grid_source": "study_area",
              "grid_extent": {"south": float(grid_lat[0]), "north": float(grid_lat[-1]),
                              "west": float(grid_lon[0]), "east": float(grid_lon[-1])}}
    params.update(extra_params or {})
    return DensityResult(grid_lat=np.asarray(grid_lat, dtype="float64"), grid_lon=np.asarray(grid_lon, dtype="float64"),
                         density=np.asarray(values, dtype="float64"), high_density_threshold=threshold, params=params)


def _inverse_mercator(y):
    return np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)


def test_overlay_bounds_follow_cell_edge_convention():
    d = _density([10.0, 10.5, 11.0], [20.0, 20.25, 20.5, 20.75], np.ones((3, 4)), 1.0)
    assert density_overlay_bounds(d) == [[9.75, 19.875], [11.25, 20.875]]   # [[south, west], [north, east]]


def test_one_node_axis_uses_params_step():
    d = _density([10.0], [20.0, 20.5], np.ones((1, 2)), 1.0, extra_params={"lat_step_deg": 0.2, "lon_step_deg": 0.5})
    assert density_overlay_bounds(d) == [[9.9, 19.75], [10.1, 20.75]]


def test_small_extent_overlay_is_the_grid_flipped_north_up():
    """City scale: Mercator rows coincide with grid rows, so the image is density[::-1]."""
    values = np.arange(12, dtype="float64").reshape(3, 4)          # unique values, max at [2, 3] (north-east)
    d = _density([23.00, 23.01, 23.02], [72.50, 72.51, 72.52, 72.53], values, threshold=6.0)
    mask = density_overlay_rgba(d, threshold_mask=True)
    assert mask.shape == (3, 4, 4) and mask.dtype == np.uint8
    expected = (values >= 6.0)[::-1]                                  # row 0 of the image = north
    assert np.array_equal(mask[..., 3] > 0, expected)
    assert tuple(mask[0, 3]) == THRESHOLD_RGBA                        # north-east cell is at top-right
    colour = density_overlay_rgba(d)
    assert tuple(colour[0, 3, :3]) == (0xF0, 0x45, 0x3A)              # grid max -> hottest colour, top-right
    assert colour[2, 0, 3] == 0                                       # value 0 (south-west) -> transparent


def test_large_extent_overlay_rows_are_placed_in_web_mercator():
    """0-60 degrees: Mercator placement differs from a plain flip; each image row must show
    the grid row nearest to the latitude at that row's centre on the Web Mercator map."""
    grid_lat = np.arange(0.0, 61.0, 10.0)                            # 7 rows, 10-degree step
    values = np.tile(np.arange(7, dtype="float64")[:, None], (1, 2)) # grid row i has value i
    d = _density(grid_lat, [0.0, 10.0], values, threshold=0.0)
    image = density_overlay_rgba(d)
    (south, _), (north, _) = density_overlay_bounds(d)

    # Independent reference: latitude at each image row's centre on a Web Mercator map,
    # and the grid row whose cell contains it.
    y_top = np.log(np.tan(np.pi / 4 + np.radians(north) / 2))
    y_bottom = np.log(np.tan(np.pi / 4 + np.radians(south) / 2))
    centres = _inverse_mercator(y_top + (np.arange(7) + 0.5) / 7 * (y_bottom - y_top))
    expected_rows = [int(np.argmin(np.abs(grid_lat - lat))) for lat in centres]
    assert all(abs(c - grid_lat[i]) <= 5.0 for c, i in zip(centres, expected_rows))   # inside that cell
    assert expected_rows != list(range(6, -1, -1))                   # a plain flip would put rows elsewhere

    # The green channel differs for each of these values, so it identifies the grid row drawn.
    green_by_value = {}
    for i in range(7):
        probe = _density([0.0], [0.0, 10.0], [[float(i), 6.0]], 0.0, extra_params={"lat_step_deg": 10.0})
        green_by_value[i] = int(density_overlay_rgba(probe)[0, 0, 1])   # value i scaled by the same max (6)
    assert len(set(green_by_value.values())) == 7
    drawn_rows = [next(i for i, g in green_by_value.items() if g == int(image[r, 0, 1])) for r in range(7)]
    assert drawn_rows == expected_rows


def test_threshold_overlay_matches_density_at_or_above_threshold():
    values = np.array([[1.0, 5.0, 9.0], [5.0, 4.999, 0.0]])
    d = _density([23.00, 23.01], [72.50, 72.51, 72.52], values, threshold=5.0)
    mask = density_overlay_rgba(d, threshold_mask=True)[..., 3] > 0
    assert np.array_equal(mask, (values >= 5.0)[::-1])               # 5.0 (equal) included, 4.999 not


def test_transparency_changes_rendering_only():
    values = np.array([[0.0, 0.5, 100.0]])
    d = _density([23.0], [72.50, 72.51, 72.52], values, 50.0, extra_params={"lat_step_deg": 0.01})
    before = d.density.copy()
    alpha = density_overlay_rgba(d)[..., 3]
    assert alpha.tolist() == [[0, 0, 230]]                            # 0 and 0.5% of max hidden; max shown
    assert np.array_equal(d.density, before)


def test_density_map_layers_legend_and_no_heatmap():
    values = np.arange(12, dtype="float64").reshape(3, 4)
    fmap = build_density_map(_density([23.00, 23.01, 23.02], [72.50, 72.51, 72.52, 72.53], values, 6.0))
    overlays = [c for c in fmap._children.values() if type(c).__name__ == "ImageOverlay"]
    assert [o.layer_name for o in overlays] == ["KDE relative density", THRESHOLD_LAYER_NAME]
    assert overlays[1].show is False and overlays[0].show is True
    assert any(type(c).__name__ == "LayerControl" for c in fmap._children.values())
    assert not any("HeatMap" in type(c).__name__ for c in fmap._children.values())
    assert sum(type(c).__name__ == "MapLegend" for c in fmap._children.values()) == 1
    assert DENSITY_LEGEND.startswith("Relative density score — not incident counts or incidents/km²")
    html = fmap.get_root().render()
    # The caption is HTML-safe JSON inside the script (e.g. —, ², and ' as ').
    assert json.dumps(html_module.escape(DENSITY_LEGEND))[1:-1].replace("&", "\\u0026").replace("'", "\\u0027") in html
    assert "relative to this analysis and grid only" in THRESHOLD_LAYER_NAME
    assert "significan" not in THRESHOLD_LAYER_NAME


def test_real_kde_peak_is_drawn_where_the_incidents_are():
    points = [(23.0200 + 0.0002 * np.sin(k), 72.5700 + 0.0002 * np.cos(k)) for k in range(25)]
    dataset = _dataset([[f"K{i}", p[0], p[1]] for i, p in enumerate(points)])
    density = run_kde(dataset, KDEParams(bandwidth_m=300, grid_cell_m=100))
    image = density_overlay_rgba(density)
    (south, west), (north, east) = density_overlay_bounds(density)
    row, col = np.unravel_index(np.argmax(image[..., 3]), image.shape[:2])    # most opaque = max
    peak_i, peak_j = np.unravel_index(np.argmax(density.density), density.density.shape)
    assert col == peak_j and row == density.density.shape[0] - 1 - peak_i
    lat_at_row = north - (row + 0.5) * (north - south) / image.shape[0]
    assert abs(lat_at_row - 23.02) < 2 * density.params["lat_step_deg"]


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"values": np.ones((2, 3))}, "shape"),
        ({"values": np.array([[1.0, np.nan], [1.0, 1.0]])}, "finite"),
        ({"threshold": float("inf")}, "threshold"),
        ({"grid_lat": [23.0, 23.01], "grid_lon": [72.5, 72.51], "n_points": None}, "n_points"),
    ],
)
def test_invalid_density_results_are_rejected(kwargs, match):
    args = {"grid_lat": [23.0, 23.01], "grid_lon": [72.5, 72.51], "values": np.ones((2, 2)), "threshold": 1.0, "n_points": 1}
    args.update(kwargs)
    d = _density(args["grid_lat"], args["grid_lon"], args["values"], args["threshold"], n_points=args["n_points"])
    with pytest.raises(AnalysisError, match=match):
        build_density_map(d)


def test_uneven_axis_cannot_be_drawn():
    d = _density([23.0, 23.01, 23.03], [72.5, 72.51], np.ones((3, 2)), 1.0)
    with pytest.raises(AnalysisError, match="evenly spaced"):
        density_overlay_bounds(d)


def test_density_map_does_not_mutate_and_is_deterministic():
    values = np.arange(12, dtype="float64").reshape(3, 4)
    d = _density([23.00, 23.01, 23.02], [72.50, 72.51, 72.52, 72.53], values, 6.0)
    before = copy.deepcopy((d.grid_lat, d.grid_lon, d.density, d.params, d.high_density_threshold))
    first, second = density_overlay_rgba(d), density_overlay_rgba(d)
    build_density_map(d)
    assert np.array_equal(first, second)
    assert density_overlay_bounds(d) == density_overlay_bounds(d)
    after = (d.grid_lat, d.grid_lon, d.density, d.params, d.high_density_threshold)
    assert all(np.array_equal(a, b) for a, b in zip(after[:3], before[:3])) and after[3:] == before[3:]


def test_layer_controls_start_collapsed_and_avoid_the_legend():
    """Stage 10B fix: collapsed layer control top-right, zoom bottom-left; layers unchanged."""
    from modules.map_visualization import LAYER_CONTROL_POSITION, ZOOM_CONTROL_POSITION

    values = np.arange(12, dtype="float64").reshape(3, 4)
    density = build_density_map(_density([23.00, 23.01, 23.02], [72.50, 72.51, 72.52, 72.53], values, 6.0))
    clusters = build_cluster_map(_two_cluster_result())
    assert (LAYER_CONTROL_POSITION, ZOOM_CONTROL_POSITION) == ("topright", "bottomleft")
    for fmap in (density, clusters):
        controls = [c for c in fmap._children.values() if type(c).__name__ == "LayerControl"]
        assert len(controls) == 1
        assert controls[0].options["collapsed"] is True and controls[0].options["position"] == "topright"
        assert '"zoomControl": false' in fmap.get_root().render() or "zoomControl: false" in fmap.get_root().render()
        assert "bottomleft" in fmap.get_root().render()
