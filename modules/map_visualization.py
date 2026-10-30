"""Folium map builders. Owner: Member 4 (GIS Visualization).

Folium expects [lat, lon] order in DEGREES (GeoJSON is [lon, lat] — do not mix).
Builders return folium.Map objects and never call Streamlit.
"""

from __future__ import annotations

import html
import math
from typing import Any

import branca.colormap as branca_cm
import folium
import numpy as np
import pandas as pd
from folium.raster_layers import ImageOverlay

from modules.contracts import (
    CLUSTER_LABEL_COLUMN,
    NOISE_LABEL,
    AnalysisError,
    CleanDataset,
    ClusterResult,
    DensityResult,
)
# Reuse the Stage 6 validators instead of duplicating them (no change to that module).
from modules.spatial_statistics import _check_cluster_result, _check_density

# Rendering cap: Leaflet becomes unusable with very many individual markers.
MAX_MAP_POINTS = 5_000
SINGLE_POINT_ZOOM = 15
POINT_STYLE = {"radius": 5, "color": "#1f4e79", "weight": 1, "fill": True, "fill_color": "#2e86c1", "fill_opacity": 0.7}

# --- cluster map ---------------------------------------------------------------
# Ten distinguishable colours (Tableau 10). Cluster label L uses CLUSTER_PALETTE[L % 10];
# with more than ten clusters colours repeat, so labels are also shown in popups/tooltips.
CLUSTER_PALETTE: tuple[str, ...] = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#bcbd22", "#17becf", "#7f7f7f",
)
NOISE_COLOR = "#616161"   # dark enough to stay visible on the grey OpenStreetMap basemap
NOISE_STYLE = {"radius": 4, "color": NOISE_COLOR, "weight": 1, "fill": True, "fill_color": NOISE_COLOR, "fill_opacity": 0.8}
CLUSTER_POINT_RADIUS = 5
CANDIDATE_OUTLINE_COLOR = "#000000"
CANDIDATE_TOOLTIP = "Candidate hotspot — size rule only (not statistical significance)"

# --- density map -----------------------------------------------------------------
DENSITY_LEGEND = "Relative density score — not incident counts or incidents/km²."
DENSITY_SCALE_NOTE = "Colours are scaled from 0 to 1 relative to this grid's maximum density score."
DENSITY_LEGEND_WIDTH_PX = 480    # fits the caption and the 2/3-width map at 1280 px (Stage 10B fix)
# Map controls (rendering only): layer controls start collapsed in the top-right corner,
# where Leaflet stacks them under the density legend; zoom moves to the bottom-left so
# neither overlaps the legend.
LAYER_CONTROL_POSITION = "topright"
ZOOM_CONTROL_POSITION = "bottomleft"
DENSITY_COLORS: tuple[str, ...] = ("#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026")
DENSITY_OPACITY = 0.65
# Cells below this fraction of the grid maximum are drawn fully transparent so the
# basemap stays visible. Rendering only: the stored density values are unchanged.
DENSITY_TRANSPARENT_BELOW = 0.01
THRESHOLD_RGBA = (49, 54, 149, 110)          # semi-transparent blue fill
THRESHOLD_LAYER_NAME = "High-density cells (≥ this run's quantile threshold — relative to this analysis and grid only)"
MAX_MERCATOR_LAT = 85.05112878               # Web Mercator latitude limit

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
    return _marker_records(frame)


def _marker_records(frame: pd.DataFrame, labels: np.ndarray | None = None) -> list[dict[str, Any]]:
    """Shared, escaped marker data for every row of `frame`, by position.

    With `labels` (DBSCAN labels by position), each record also carries
    `cluster_label` and the popup gains a "DBSCAN" line after the incident ID.
    Without it the output is exactly the Stage 3 incident-marker format.
    """
    lats = frame["latitude"].to_numpy(dtype="float64")
    lons = frame["longitude"].to_numpy(dtype="float64")
    ids = frame["incident_id"].to_numpy()
    present = [(col, label) for col, label in _POPUP_FIELDS if col in frame.columns]
    extras = {col: frame[col].tolist() for col, _ in present}  # tolist keeps pd.Timestamp

    records = []
    for pos in range(len(frame)):
        incident_id = str(ids[pos])
        lines = [f"<b>Incident</b>: {html.escape(incident_id)}"]
        if labels is not None:
            label = int(labels[pos])
            lines.append(f"<b>DBSCAN</b>: {'noise' if label == NOISE_LABEL else f'cluster {label}'}")
        for col, label_text in present:
            text = _display(extras[col][pos])
            if text is not None:
                lines.append(f"<b>{label_text}</b>: {html.escape(text)}")
        lines.append(f"<b>Lat, Lon</b>: {lats[pos]:.6f}, {lons[pos]:.6f}")
        record = {
            "incident_id": incident_id,
            "lat": float(lats[pos]),
            "lon": float(lons[pos]),
            "source_row": int(frame.index[pos]),
            "tooltip": html.escape(incident_id),
            "popup_html": "<br>".join(lines),
        }
        if labels is not None:
            record["cluster_label"] = int(labels[pos])
        records.append(record)
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


def cluster_color(label: int) -> str:
    """Deterministic display colour for a DBSCAN label (grey for noise)."""
    return NOISE_COLOR if label == NOISE_LABEL else CLUSTER_PALETTE[label % len(CLUSTER_PALETTE)]


def cluster_marker_records(
    result: ClusterResult,
    max_points: int | None = MAX_MAP_POINTS,
    point_mask: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Escaped marker data for displayed incidents of a DBSCAN result.

    `point_mask` is an optional boolean array by POSITION (display filter); the
    cap is applied after it: the first `max_points` selected rows in file order.
    Each record has the incident-marker keys plus `cluster_label`.
    Raises AnalysisError for an empty or inconsistent result.
    """
    frame, labels = _cluster_frame(result)
    selected = np.arange(len(frame)) if point_mask is None else np.flatnonzero(_mask(point_mask, len(frame)))
    if max_points is not None:
        selected = selected[:max_points]
    return _marker_records(frame.iloc[selected], labels[selected])


def build_cluster_map(
    result: ClusterResult,
    max_points: int | None = MAX_MAP_POINTS,
    point_mask: np.ndarray | None = None,
    cluster_labels: set[int] | None = None,
) -> folium.Map:
    """DBSCAN map: points coloured by cluster, noise grey, every cluster's circle.

    - Points: at most `max_points` markers (cap applied before markers are
      built, after the optional positional `point_mask`). Cluster members use
      cluster_color(label); noise uses smaller grey markers.
    - Circles: one per cluster in `result.clusters` (or the subset in
      `cluster_labels`), centred at the reported centroid with the reported
      radius_m in metres — drawn regardless of the point cap. Candidate
      hotspots get a thick black outline and CANDIDATE_TOOLTIP.
    - The view fits all cluster circles and drawn points. Nothing is recomputed:
      centroids, radii and flags come from the DBSCAN summaries.
    Raises AnalysisError for an empty or inconsistent result.
    """
    records = cluster_marker_records(result, max_points, point_mask)
    summaries = [c for c in result.clusters if cluster_labels is None or c.cluster_label in cluster_labels]

    lats = [r["lat"] for r in records] + [c.centroid_lat for c in summaries]
    lons = [r["lon"] for r in records] + [c.centroid_lon for c in summaries]
    frame, _ = _cluster_frame(result)
    if not lats:  # everything filtered out: centre on the data without drawing anything
        lats = frame["latitude"].to_numpy(dtype="float64").tolist()
        lons = frame["longitude"].to_numpy(dtype="float64").tolist()
    south, north, west, east = min(lats), max(lats), min(lons), max(lons)
    fmap = folium.Map(location=[(south + north) / 2, (west + east) / 2], zoom_start=SINGLE_POINT_ZOOM, control_scale=True,
                      zoom_control=ZOOM_CONTROL_POSITION)

    circles = folium.FeatureGroup(name="Cluster extents (centroid + radius_m)")
    for c in summaries:
        color = cluster_color(c.cluster_label)
        tooltip = f"Cluster {c.cluster_label}: {c.incident_count} incidents, radius {c.radius_m:.0f} m"
        if c.is_candidate_hotspot:
            tooltip = f"{tooltip} — {CANDIDATE_TOOLTIP}"
        folium.Circle(
            location=[c.centroid_lat, c.centroid_lon],
            radius=float(c.radius_m),
            color=CANDIDATE_OUTLINE_COLOR if c.is_candidate_hotspot else color,
            weight=4 if c.is_candidate_hotspot else 1,
            fill=True,
            fill_color=color,
            fill_opacity=0.15,
            tooltip=folium.Tooltip(html.escape(tooltip)),
        ).add_to(circles)
    circles.add_to(fmap)

    points = folium.FeatureGroup(name="Incidents (cluster colour; grey = noise)")
    for rec in records:
        label = rec["cluster_label"]
        if label == NOISE_LABEL:
            style = NOISE_STYLE
        else:
            color = cluster_color(label)
            style = {**POINT_STYLE, "radius": CLUSTER_POINT_RADIUS, "color": color, "fill_color": color}
        folium.CircleMarker(
            location=[rec["lat"], rec["lon"]],
            tooltip=folium.Tooltip(rec["tooltip"]),
            popup=folium.Popup(rec["popup_html"], max_width=320),
            **style,
        ).add_to(points)
    points.add_to(fmap)
    folium.LayerControl(collapsed=True, position=LAYER_CONTROL_POSITION).add_to(fmap)
    if (south, west) != (north, east):
        fmap.fit_bounds([[south, west], [north, east]], padding=(20, 20))
    return fmap


def density_overlay_bounds(result: DensityResult) -> list[list[float]]:
    """Folium bounds [[south, west], [north, east]] of the KDE cells, in degrees.

    Each grid node is the centre of a cell one step wide, so the overlay spans
    from half a step before the first node to half a step after the last node
    on each axis (steps from the axes, or params lat/lon_step_deg for a one-node
    axis). Latitudes are clipped to the Web Mercator limit (+/-85.0511).
    """
    _check_density(result, result.params.get("n_points"))
    lat_step = _axis_step(result.grid_lat, result.params.get("lat_step_deg"), "grid_lat")
    lon_step = _axis_step(result.grid_lon, result.params.get("lon_step_deg"), "grid_lon")
    south = max(-MAX_MERCATOR_LAT, float(result.grid_lat[0]) - lat_step / 2)
    north = min(MAX_MERCATOR_LAT, float(result.grid_lat[-1]) + lat_step / 2)
    west = float(result.grid_lon[0]) - lon_step / 2
    east = float(result.grid_lon[-1]) + lon_step / 2
    return [[south, west], [north, east]]


def density_overlay_rgba(result: DensityResult, threshold_mask: bool = False) -> np.ndarray:
    """RGBA uint8 image of the KDE grid, ready for an ImageOverlay with origin="upper".

    Orientation: image row 0 is the NORTH edge; image column c is grid column c
    (longitude is linear in Web Mercator). Leaflet stretches an overlay linearly
    in Web Mercator, so each image row r is placed at the Mercator y of its
    centre, converted back to latitude, and filled from the nearest grid row
    (exact ties -> the southern row). Image height equals len(grid_lat).

    Colour: density / grid maximum on DENSITY_COLORS, alpha DENSITY_OPACITY,
    fully transparent below DENSITY_TRANSPARENT_BELOW of the maximum (all
    transparent if the maximum is 0). With threshold_mask=True the image instead
    marks cells with density >= high_density_threshold in THRESHOLD_RGBA.
    The DensityResult is not modified.
    """
    bounds = density_overlay_bounds(result)
    rows = _mercator_row_index(np.asarray(result.grid_lat, dtype="float64"), bounds[0][0], bounds[1][0])
    grid = np.asarray(result.density, dtype="float64")[rows, :]       # (height, n_lon), north first
    image = np.zeros(grid.shape + (4,), dtype=np.uint8)
    if threshold_mask:
        image[grid >= result.high_density_threshold] = THRESHOLD_RGBA
        return image
    peak = float(np.asarray(result.density).max())
    if peak <= 0:
        return image
    scaled = grid / peak
    stops = np.linspace(0.0, 1.0, len(DENSITY_COLORS))       # same stops as the legend colormap
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in DENSITY_COLORS], dtype="float64")
    for channel in range(3):
        image[..., channel] = np.rint(np.interp(scaled, stops, rgb[:, channel])).astype(np.uint8)
    image[..., 3] = np.where(scaled >= DENSITY_TRANSPARENT_BELOW, round(255 * DENSITY_OPACITY), 0)
    return image


def build_density_map(result: DensityResult) -> folium.Map:
    """KDE map: the existing density grid as an image overlay plus a threshold layer.

    No estimator is run: the DensityResult values are displayed as-is via
    density_overlay_rgba / density_overlay_bounds (mercator_project=False,
    because the rows are already placed in Web Mercator). Adds the legend
    DENSITY_LEGEND, a toggleable THRESHOLD_LAYER_NAME overlay (hidden by
    default) and a layer control. Raises AnalysisError for an invalid result.
    """
    bounds = density_overlay_bounds(result)
    (south, west), (north, east) = bounds
    fmap = folium.Map(location=[(south + north) / 2, (west + east) / 2], zoom_start=SINGLE_POINT_ZOOM, control_scale=True,
                      zoom_control=ZOOM_CONTROL_POSITION)
    ImageOverlay(
        image=density_overlay_rgba(result), bounds=bounds, origin="upper", mercator_project=False,
        pixelated=True, name="KDE relative density", overlay=True, control=True, show=True,
    ).add_to(fmap)
    ImageOverlay(
        image=density_overlay_rgba(result, threshold_mask=True), bounds=bounds, origin="upper",
        mercator_project=False, pixelated=True, name=THRESHOLD_LAYER_NAME, overlay=True, control=True, show=False,
    ).add_to(fmap)
    _density_colormap().add_to(fmap)
    folium.LayerControl(collapsed=True, position=LAYER_CONTROL_POSITION).add_to(fmap)
    fmap.fit_bounds(bounds)
    return fmap


def _cluster_frame(result: ClusterResult) -> tuple[pd.DataFrame, np.ndarray]:
    frame = result.labeled_frame
    if frame.empty:
        raise AnalysisError("No clustered incidents to map: the cluster result is empty.")
    _check_cluster_result(result)
    return frame, frame[CLUSTER_LABEL_COLUMN].to_numpy()


def _mask(point_mask: np.ndarray, n: int) -> np.ndarray:
    mask = np.asarray(point_mask)
    if mask.dtype != bool or mask.shape != (n,):
        raise AnalysisError(f"point_mask must be a boolean array of length {n} (one entry per row, by position).")
    return mask


def _axis_step(axis: np.ndarray, fallback: Any, name: str) -> float:
    axis = np.asarray(axis, dtype="float64")
    if axis.size > 1:
        steps = np.diff(axis)
        if not np.allclose(steps, steps[0], rtol=1e-9, atol=0.0):
            raise AnalysisError(f"Density {name} must be evenly spaced to be drawn as an image.")
        return float(steps[0])
    if isinstance(fallback, (int, float)) and math.isfinite(fallback) and fallback > 0:
        return float(fallback)
    raise AnalysisError(f"Density {name} has one node and no valid step in params; cannot size the overlay.")


def _mercator_y(lat: np.ndarray | float) -> np.ndarray:
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def _mercator_row_index(grid_lat: np.ndarray, south: float, north: float) -> np.ndarray:
    """Grid row for each image row (north first), placing rows linearly in Mercator y."""
    height = grid_lat.size
    if height == 1:
        return np.zeros(1, dtype=np.intp)
    y_top, y_bottom = _mercator_y(north), _mercator_y(south)
    y_centres = y_top + (np.arange(height) + 0.5) / height * (y_bottom - y_top)
    lat_centres = np.degrees(2 * np.arctan(np.exp(y_centres)) - np.pi / 2)
    upper = np.clip(np.searchsorted(grid_lat, lat_centres, side="left"), 1, grid_lat.size - 1)
    lower = upper - 1
    choose_lower = (lat_centres - grid_lat[lower]) <= (grid_lat[upper] - lat_centres)
    return np.where(choose_lower, lower, upper)


def _density_colormap() -> branca_cm.LinearColormap:
    colormap = branca_cm.LinearColormap(list(DENSITY_COLORS), vmin=0.0, vmax=1.0, caption=DENSITY_LEGEND)
    colormap.width = DENSITY_LEGEND_WIDTH_PX   # branca's 450 px default clips the caption
    return colormap


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
