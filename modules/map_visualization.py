"""Folium map builders. Owner: Member 4 (GIS Visualization).

Folium expects [lat, lon] order in DEGREES (GeoJSON is [lon, lat] — do not mix).
Builders return folium.Map objects and never call Streamlit.
"""

from __future__ import annotations

import html
from typing import Any

import folium
import pandas as pd

from modules.contracts import AnalysisError, CleanDataset, ClusterResult, DensityResult

# Rendering cap: Leaflet becomes unusable with very many individual markers.
MAX_MAP_POINTS = 5_000
SINGLE_POINT_ZOOM = 15
POINT_STYLE = {"radius": 5, "color": "#1f4e79", "weight": 1, "fill": True, "fill_color": "#2e86c1", "fill_opacity": 0.7}

# Optional columns shown in popups, in this order, with their labels.
_POPUP_FIELDS: tuple[tuple[str, str], ...] = (
    ("incident_date", "Date"),
    ("incident_type", "Type"),
    ("severity", "Severity"),
    ("location_name", "Location"),
)


def incident_marker_records(dataset: CleanDataset, max_points: int | None = MAX_MAP_POINTS) -> list[dict[str, Any]]:
    """Plain marker data for the first `max_points` accepted incidents (file order).

    Coordinates are read by row POSITION; the frame's index label is carried
    only as `source_row` for traceability. Every user-supplied value in
    `tooltip` and `popup_html` is HTML-escaped. Returns dicts with keys:
    incident_id, lat, lon, source_row, tooltip, popup_html.

    Raises AnalysisError if the dataset is unusable or has no rows.
    """
    _require_points(dataset)
    frame = dataset.frame if max_points is None else dataset.frame.iloc[:max_points]
    lats = frame["latitude"].to_numpy(dtype="float64")
    lons = frame["longitude"].to_numpy(dtype="float64")
    ids = frame["incident_id"].to_numpy()
    present = [(col, label) for col, label in _POPUP_FIELDS if col in frame.columns]
    extras = {col: frame[col].tolist() for col, _ in present}  # tolist keeps pd.Timestamp

    records = []
    for pos in range(len(frame)):
        incident_id = str(ids[pos])
        lines = [f"<b>Incident</b>: {html.escape(incident_id)}"]
        for col, label in present:
            text = _display(extras[col][pos])
            if text is not None:
                lines.append(f"<b>{label}</b>: {html.escape(text)}")
        lines.append(f"<b>Lat, Lon</b>: {lats[pos]:.6f}, {lons[pos]:.6f}")
        records.append(
            {
                "incident_id": incident_id,
                "lat": float(lats[pos]),
                "lon": float(lons[pos]),
                "source_row": int(frame.index[pos]),
                "tooltip": html.escape(incident_id),
                "popup_html": "<br>".join(lines),
            }
        )
    return records


def build_incident_map(dataset: CleanDataset, max_points: int | None = MAX_MAP_POINTS) -> folium.Map:
    """Point layer of the accepted incidents (no clustering or density).

    The view fits the bounding box of the plotted points (a single point is
    centred at SINGLE_POINT_ZOOM); there is no hard-coded fallback location.
    At most `max_points` markers are drawn, first in file order; callers should
    tell the user when len(dataset.frame) > max_points. Marker order and
    positions are deterministic for a fixed input (folium's internal element
    ids are random and are not part of the contract).

    Raises AnalysisError if the dataset is unusable or has no rows.
    """
    records = incident_marker_records(dataset, max_points)
    lats = [r["lat"] for r in records]
    lons = [r["lon"] for r in records]
    south, north, west, east = min(lats), max(lats), min(lons), max(lons)

    fmap = folium.Map(location=[(south + north) / 2, (west + east) / 2], zoom_start=SINGLE_POINT_ZOOM, control_scale=True)
    layer = folium.FeatureGroup(name="Incidents")
    for rec in records:
        folium.CircleMarker(
            location=[rec["lat"], rec["lon"]],
            tooltip=folium.Tooltip(rec["tooltip"]),
            popup=folium.Popup(rec["popup_html"], max_width=320),
            **POINT_STYLE,
        ).add_to(layer)
    layer.add_to(fmap)
    if (south, west) != (north, east):
        fmap.fit_bounds([[south, west], [north, east]], padding=(20, 20))
    return fmap


def build_cluster_map(result: ClusterResult) -> "folium.Map":
    """Points coloured by cluster, noise greyed, candidate hotspots outlined. Stage 7."""
    raise NotImplementedError("Stage 7: map_visualization.build_cluster_map")


def build_density_map(result: DensityResult) -> "folium.Map":
    """KDE surface overlay, labelled as estimated density. Stage 7."""
    raise NotImplementedError("Stage 7: map_visualization.build_density_map")


def _require_points(dataset: CleanDataset) -> None:
    if not dataset.report.is_usable or dataset.frame.empty:
        raise AnalysisError("No valid incidents to map: the dataset is unusable or empty.")


def _display(value: Any) -> str | None:
    """Readable text for a popup value; None for missing values."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if value == value.normalize() else value.isoformat(sep=" ")
    text = str(value)
    return text if text.strip() else None
