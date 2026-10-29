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
