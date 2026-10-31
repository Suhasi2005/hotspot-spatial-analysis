"""Streamlit page renderers. Owner: Member 4 (Dashboard).

The only module (besides app.py) allowed to import Streamlit. Pages read from
AnalysisRun / CleanDataset objects and call app_controller; they hold no
analytical logic.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from config.settings import DB_PATH, DEFAULT_ANALYSIS_CONFIG, REPORTS_DIR, AnalysisConfig, CandidateHotspotCriteria, DBSCANParams, KDEParams
from modules.app_controller import (
    cluster_dataset,
    estimate_density,
    generate_reports,
    load_and_validate,
    record_run,
    summarize_results,
)
from modules.database import list_runs, resolve_report_path
from modules.report_generator import CSV_SAFETY_WARNING
from modules.contracts import CLUSTER_LABEL_COLUMN, NOISE_LABEL, AnalysisError, CleanDataset, ClusterResult, DataValidationError
from modules.data_manager import list_sample_datasets
from modules.data_validator import summarize_quality
from modules.map_visualization import (
    DENSITY_LEGEND,
    DENSITY_SCALE_NOTE,
    DENSITY_TRANSPARENT_BELOW,
    MAX_MAP_POINTS,
    build_cluster_map,
    build_density_map,
    build_incident_map,
    cluster_color,
)
from modules.spatial_statistics import incidents_by_period
from modules.ui_theme import (
    ACCENT,
    KPI_KEY_PREFIX,
    SUMMARY_KPI_KEY,
    SUMMARY_PANEL_PREFIX,
    bar_chart_layout,
    plotly_template,
)

PAGES: tuple[str, ...] = ("Data", "Clusters (DBSCAN)", "Density (KDE)", "Summary", "History & Reports")
ANALYSIS_PAGES: tuple[str, ...] = ("Clusters (DBSCAN)", "Density (KDE)", "Summary")
PREVIEW_ROWS = 100
MISSING_LABEL = "(missing)"
NOT_RUN = "Not run"
CACHE_KEY = "analysis_cache"
# History database used by the Save button and the History page. Read at call
# time so tests can point it at a temporary file; the app run itself can be
# redirected with the HOTSPOT_DB_PATH environment variable (config.settings).
HISTORY_DB_PATH = DB_PATH
HISTORY_LIMIT = 50
# Reports root for generation and downloads; read at call time (tests patch it,
# the app can be redirected with HOTSPOT_REPORTS_DIR).
HISTORY_REPORTS_DIR = REPORTS_DIR
REPORT_MIME = {".csv": "text/csv", ".pdf": "application/pdf"}

# --- analysis pages (Stage 10B Phase 3) -------------------------------------------------
FILTERS_LABEL = "Display filters — visualization only; analysis results remain unchanged."
KDE_DISCLAIMER = ("KDE values are relative density scores. They are not incident counts or "
                  "incidents per square kilometre.")
MAP_PANEL_RATIO = (2, 1)          # map : explanation panel on the Clusters and Density pages

# --- Summary page (Stage 10B Phase 4.3) ---------------------------------------------------
SUMMARY_TABS = ("Method Comparison", "Distributions", "Notes & Limitations")
SYNTHETIC_NOTICE = ("Synthetic demonstration data: every record is artificial. These results show how the "
                    "methods work and are not real-world incident statistics.")

# --- application shell (Stage 10B Phase 2) ---------------------------------------------
BRAND_NAME = "Hotspot Analytics"
BRAND_TAGLINE = "Spatial Incident Analysis"
KPI_PER_ROW = 4
# Page name (as used by render_page and the tests) -> navigation label, Material icon,
# URL path and the one-line description shown under the page title.
PAGE_INFO: dict[str, tuple[str, str, str, str]] = {
    "Data": ("Data", ":material/upload_file:", "data", "Import and validate incident datasets."),
    "Clusters (DBSCAN)": ("Clusters", ":material/hub:", "clusters", "Discover spatial clusters using DBSCAN."),
    "Density (KDE)": ("Density", ":material/blur_on:", "density", "Explore relative spatial density using KDE."),
    "Summary": ("Summary", ":material/insights:", "summary", "Compare analytical methods and review results."),
    "History & Reports": ("History & Reports", ":material/history:", "history",
                          "Access saved analyses and generated reports."),
}


def render_page(name: str) -> None:
    """Render one page plus the sidebar dataset-status block.

    The status block is created first (so it sits under the navigation) and
    filled after the page has run, so it reflects this run's dataset and
    analysis results.
    """
    status_box = st.sidebar.container()
    try:
        _render_page_body(name)
    finally:
        _render_dataset_status(status_box)


def _render_page_body(name: str) -> None:
    if name == "Data":
        render_data_page()
        return
    if name == "History & Reports":
        _render_history_page()
        return
    if name not in ANALYSIS_PAGES:
        st.header(name)
        st.info("Not implemented yet — see docs/development_plan.md for the stage that builds this page.")
        return

    config = _sidebar_config()
    _page_header(name)
    dataset = st.session_state.get("dataset")
    if dataset is None:
        st.info("No dataset loaded. Load and validate a CSV on the Data page first.", icon=":material/upload_file:")
        return
    if not dataset.report.is_usable:
        st.warning("The loaded dataset is unusable (no accepted incidents), so no analysis runs. Fix it on the Data page.",
                   icon=":material/report:")
        return
    if config is None:
        st.error("Analysis parameters are invalid; fix them in the sidebar. No analysis was run.", icon=":material/tune:")
        return
    results = _analysis_results(dataset, config)
    if name == "Clusters (DBSCAN)":
        _render_clusters_page(results)
    elif name == "Density (KDE)":
        _render_density_page(results)
    else:
        _render_summary_page(dataset, results)


def _page_header(name: str) -> None:
    """Page title (unchanged text) plus its one-line description."""
    st.header(name)
    st.caption(PAGE_INFO[name][3])


def kpi_strip(items: list[tuple[str, str]]) -> None:
    """KPI cards from (label, value) pairs, at most KPI_PER_ROW per row.

    Values are shown exactly as given; callers pass existing values only and use
    NOT_RUN when an analysis has not produced one.

    Each card is an st.metric inside a keyed container (see kpi_key) that
    ui_theme.SHELL_CSS styles as a white card; status values become a coloured
    badge whose text still states the status.
    """
    for row in kpi_rows(items):
        for column, (label, value) in zip(st.columns(KPI_PER_ROW), row):
            with column.container(key=kpi_key(label, value)):
                st.metric(label, value)


def kpi_grid(items: list[tuple[str, str]], key: str) -> None:
    """KPI cards in a wrapping row: same cards as kpi_strip, but two across on phones."""
    with st.container(horizontal=True, wrap=True, key=key):
        for label, value in items:
            with st.container(key=kpi_key(label, value)):
                st.metric(label, value)


def _render_dataset_status(box) -> None:
    """Sidebar summary of the current dataset and last analysis (session state only)."""
    dataset = st.session_state.get("dataset")
    with box:
        st.markdown("**Dataset**")
        if dataset is None:
            st.caption("No dataset loaded.")
            return
        report = dataset.report
        entry = st.session_state.get(CACHE_KEY)
        current = entry if entry is not None and entry.get("dataset") is dataset else None
        lines = [
            escape_markdown(dataset.source_name),
            f"Rows {report.total_rows:,} · Accepted {report.valid_rows:,} · Rejected {report.rejected_rows:,}",
            f"Analysis: {analysis_status(current) if report.is_usable else 'Dataset unusable'}",
        ]
        if current is not None and current.get("saved_run_id"):
            lines.append(f"Saved run: {current['saved_run_id'][:8]}")
        st.caption("  \n".join(lines))


# --- pure helpers (no Streamlit) ---------------------------------------------------


def display_mask(
    frame: pd.DataFrame,
    severities: set[str] | None = None,
    incident_types: set[str] | None = None,
    show_noise: bool = True,
    candidate_labels: set[int] | None = None,
) -> np.ndarray:
    """Boolean array by POSITION selecting the incidents to DISPLAY.

    Display-only: it never changes the frame or any analysis result.
    - severities / incident_types: keep rows whose value is in the set (missing
      values match MISSING_LABEL); None means no filter. Ignored when the column
      is absent.
    - show_noise=False hides rows with cluster_label == -1.
    - candidate_labels: when given, keep only rows in those clusters.
    """
    mask = np.ones(len(frame), dtype=bool)
    for column, allowed in (("severity", severities), ("incident_type", incident_types)):
        if allowed is not None and column in frame.columns:
            mask &= category_values(frame[column]).isin(allowed).to_numpy()
    labels = frame[CLUSTER_LABEL_COLUMN].to_numpy() if CLUSTER_LABEL_COLUMN in frame.columns else None
    if labels is not None and not show_noise:
        mask &= labels != NOISE_LABEL
    if labels is not None and candidate_labels is not None:
        mask &= np.isin(labels, list(candidate_labels))
    return mask


def category_values(series: pd.Series) -> pd.Series:
    """Values as strings with missing values as MISSING_LABEL (display only)."""
    return series.astype(object).where(series.notna(), MISSING_LABEL).map(str)


def analysis_cache_key(config: AnalysisConfig) -> tuple:
    """Hashable key of every parameter that affects DBSCAN, KDE or the summary."""
    return tuple(sorted((k, repr(v)) for k, v in asdict(config).items()))


STATUS_KPI_LABELS = ("Analysis status", "Validation status")


def kpi_tone(label: str, value: str) -> str | None:
    """Badge tone for a status KPI (success / warning / error / info); None for other KPIs.

    Display only: the value text itself is unchanged and always shown.
    """
    if label not in STATUS_KPI_LABELS:
        return None
    if value in ("Complete", "Ready"):
        return "success"
    if value.startswith("Partial") or value == "Ready with rejections":
        return "warning"
    if value in ("Failed", "Unusable", "Dataset unusable"):
        return "error"
    return "info"                                                      # NOT_RUN and anything unexpected


def kpi_key(label: str, value: str) -> str:
    """Container key for one KPI card; status cards carry their badge tone for the CSS."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in label.lower())
    tone = kpi_tone(label, value)
    return f"{KPI_KEY_PREFIX}{f'badge_{tone}_' if tone else 'card_'}{slug}"


def is_synthetic_source(name: str) -> bool:
    """True for files named as synthetic (data/sample/README.md requires it in the file name)."""
    return "synthetic" in name.lower()


def kpi_rows(items: list[tuple[str, str]], per_row: int = KPI_PER_ROW) -> list[list[tuple[str, str]]]:
    """Split KPI (label, value) pairs into rows of at most `per_row`."""
    return [items[i:i + per_row] for i in range(0, len(items), per_row)]


def analysis_status(entry: dict[str, Any] | None) -> str:
    """Plain status of an analysis cache entry: NOT_RUN, Complete, Partial or Failed."""
    if entry is None:
        return NOT_RUN
    if entry.get("cluster_error") and entry.get("density_error"):
        return "Failed"
    if entry.get("cluster_error"):
        return "Partial — DBSCAN failed"
    if entry.get("density_error"):
        return "Partial — KDE failed"
    if entry.get("summary_error"):
        return "Partial — summary failed"
    return "Complete"


_MARKDOWN_SPECIAL = set("\\`*_{}[]()#+-.!|~<>$")


def escape_markdown(text: str) -> str:
    """Backslash-escape Markdown/LaTeX characters so user text renders literally."""
    return "".join("\\" + ch if ch in _MARKDOWN_SPECIAL else ch for ch in str(text))


# --- analysis lifecycle ----------------------------------------------------------------


def _sidebar_config() -> AnalysisConfig | None:
    """Analysis parameters from the sidebar; defaults from config; validated by the dataclasses."""
    d = DEFAULT_ANALYSIS_CONFIG
    sb = st.sidebar.expander("Analysis parameters", icon=":material/tune:")
    sb.caption("Changing these re-runs DBSCAN and KDE on all accepted incidents.")
    eps_m = sb.number_input("DBSCAN eps_m (metres)", value=float(d.dbscan.eps_m), step=50.0, key="p_eps_m")
    min_samples = sb.number_input("DBSCAN min_samples", value=int(d.dbscan.min_samples), step=1, key="p_min_samples")
    min_incidents = sb.number_input("Candidate min_incidents", value=int(d.hotspot.min_incidents), step=1, key="p_min_incidents")
    bandwidth_m = sb.number_input("KDE bandwidth_m (metres)", value=float(d.kde.bandwidth_m), step=50.0, key="p_bandwidth_m")
    grid_cell_m = sb.number_input("KDE grid_cell_m (metres)", value=float(d.kde.grid_cell_m), step=25.0, key="p_grid_cell_m")
    quantile = sb.number_input("KDE high_density_quantile", value=float(d.kde.high_density_quantile), step=0.01,
                               format="%.3f", key="p_quantile")
    try:
        return AnalysisConfig(
            dbscan=DBSCANParams(eps_m=float(eps_m), min_samples=int(min_samples)),
            kde=KDEParams(bandwidth_m=float(bandwidth_m), kernel=d.kde.kernel, grid_cell_m=float(grid_cell_m),
                          high_density_quantile=float(quantile)),
            hotspot=CandidateHotspotCriteria(min_incidents=int(min_incidents),
                                             min_density_per_km2=d.hotspot.min_density_per_km2),
            study_area=d.study_area,
            random_seed=d.random_seed,
        )
    except ValueError as exc:
        sb.error(f"Invalid parameter: {exc}")
        return None


def _analysis_results(dataset: CleanDataset, config: AnalysisConfig) -> dict[str, Any]:
    """DBSCAN, KDE and summary for (dataset, parameters), cached in session state.

    The cache entry is reused only when it holds this exact dataset object and
    the same parameter key; otherwise everything is recomputed. Each analysis
    can fail independently; its AnalysisError message is kept for display.
    """
    key = analysis_cache_key(config)
    cached = st.session_state.get(CACHE_KEY)
    if cached is not None and cached["dataset"] is dataset and cached["key"] == key:
        return cached
    entry: dict[str, Any] = {"dataset": dataset, "key": key, "config": config,
                             "clusters": None, "cluster_error": None, "density": None, "density_error": None,
                             "summary": None, "summary_error": None}
    with st.spinner("Running DBSCAN clustering… Please wait."):
        try:
            entry["clusters"] = cluster_dataset(dataset, config)
        except AnalysisError as exc:
            entry["cluster_error"] = str(exc)
    with st.spinner("Running KDE density estimation… Please wait."):
        try:
            entry["density"] = estimate_density(dataset, config)
        except AnalysisError as exc:
            entry["density_error"] = str(exc)
    with st.spinner("Summarising results…"):
        try:
            entry["summary"] = summarize_results(dataset, entry["clusters"], entry["density"])
        except AnalysisError as exc:
            entry["summary_error"] = str(exc)
    st.session_state[CACHE_KEY] = entry
    return entry


# --- Clusters page ----------------------------------------------------------------------


def _render_clusters_page(results: dict[str, Any]) -> None:
    if results["cluster_error"]:
        kpi_strip([("Clusters", NOT_RUN), ("Candidate hotspots", NOT_RUN), ("Noise incidents", NOT_RUN),
                   ("Noise share", NOT_RUN)])
        st.error(f"DBSCAN failed: {results['cluster_error']}")
        return
    clusters: ClusterResult = results["clusters"]
    frame = clusters.labeled_frame
    candidates = {c.cluster_label for c in clusters.clusters if c.is_candidate_hotspot}
    summary = results["summary"]
    noise_share = NOT_RUN if summary is None or summary.noise_share is None else f"{summary.noise_share:.1%}"

    kpi_strip([
        ("Clusters", str(len(clusters.clusters))),
        ("Candidate hotspots", str(len(candidates))),
        ("Noise incidents", f"{clusters.noise_count:,} of {len(frame):,}"),
        ("Noise share", noise_share),
    ])

    filters = st.sidebar.expander(FILTERS_LABEL, expanded=True, icon=":material/filter_alt:")
    filters.caption("Change only what the cluster map and the 'shown' bars display. "
                    "DBSCAN, KDE and the summary always use all accepted incidents.")
    severities = _category_filter(filters, frame, "severity", "Severity (display only)")
    types = _category_filter(filters, frame, "incident_type", "Incident type (display only)")
    show_noise = filters.checkbox("Show noise points", value=True, key="f_show_noise")
    candidates_only = filters.checkbox("Candidate hotspots only", value=False, key="f_candidates_only")

    mask = display_mask(frame, severities, types, show_noise, candidates if candidates_only else None)
    shown = int(mask.sum())
    map_col, info_col = st.columns(MAP_PANEL_RATIO, gap="medium")
    with map_col:
        if shown > MAX_MAP_POINTS:
            st.warning(
                f"Only the first {MAX_MAP_POINTS:,} of {shown:,} selected incidents (in file order) are drawn as points. "
                "This is NOT a representative sample. Every cluster circle is still drawn."
            )
        else:
            st.caption(f"Showing {shown:,} of {len(frame):,} accepted incidents under the current display filters.")
        st_folium(
            build_cluster_map(clusters, MAX_MAP_POINTS, mask, candidates if candidates_only else None),
            height=520, use_container_width=True, returned_objects=[], key="cluster_map",
        )
    with info_col:
        _cluster_explanation(results["config"])

    if not clusters.clusters:
        st.info("DBSCAN found no clusters with these parameters; every incident is noise.")
        return
    labels = frame[CLUSTER_LABEL_COLUMN].to_numpy()
    table = pd.DataFrame(
        [
            {
                "cluster": c.cluster_label,
                "incidents": c.incident_count,
                "shown under filters": int(np.count_nonzero(mask & (labels == c.cluster_label))),
                "centroid lat": round(c.centroid_lat, 6),
                "centroid lon": round(c.centroid_lon, 6),
                "radius_m": round(c.radius_m, 1),
                "candidate hotspot (size rule)": "yes" if c.is_candidate_hotspot else "no",
            }
            for c in clusters.clusters
        ]
    )
    st.subheader("Cluster summaries")
    table_tab, chart_tab = st.tabs(["Table", "Cluster sizes"])
    with table_tab:
        st.dataframe(
            table, hide_index=True, width="stretch",
            column_config={
                "cluster": st.column_config.NumberColumn("Cluster", help="An identifier, not a rank", format="%d"),
                "incidents": st.column_config.NumberColumn("Incidents", format="%d"),
                "shown under filters": st.column_config.NumberColumn("Shown under filters", format="%d"),
                "centroid lat": st.column_config.NumberColumn("Centroid lat", format="%.6f"),
                "centroid lon": st.column_config.NumberColumn("Centroid lon", format="%.6f"),
                "radius_m": st.column_config.NumberColumn("Radius (m)", format="%.1f"),
                "candidate hotspot (size rule)": st.column_config.TextColumn("Candidate hotspot (size rule)"),
            },
        )
    with chart_tab:
        fig = go.Figure(
            [
                go.Bar(name="All members (analysis)", x=table["cluster"].astype(str), y=table["incidents"],
                       marker_color=[cluster_color(c) for c in table["cluster"]],
                       marker_line_color=["#000000" if c in candidates else "rgba(0,0,0,0)" for c in table["cluster"]],
                       marker_line_width=3),
                go.Bar(name="Shown under display filters", x=table["cluster"].astype(str), y=table["shown under filters"],
                       marker_color="#bbbbbb"),
            ]
        )
        # Short wrapped title, legend below the plot and automargins so nothing is
        # clipped or overlapped at phone width; data and bar colours are unchanged.
        fig.update_layout(template=plotly_template(), barmode="group",
                          title={"text": "Cluster sizes<br><sup>Black outline = candidate hotspot (size rule only)</sup>",
                                 "x": 0, "xanchor": "left", "y": 0.97, "yanchor": "top"},
                          xaxis_title="Cluster label (an identifier, not a rank)", yaxis_title="Incidents",
                          legend={"orientation": "h", "x": 0, "xanchor": "left", "y": -0.3, "yanchor": "top"},
                          margin={"l": 48, "r": 16, "t": 64, "b": 96}, height=400)
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True)
        st.plotly_chart(fig, width="stretch", key="chart_cluster_sizes")


def _cluster_explanation(config: AnalysisConfig) -> None:
    """Legend and method notes beside the cluster map, using this run's parameters."""
    with st.container(border=True):
        st.markdown("**How to read this map**")
        st.markdown(
            "- **Coloured points:** members of a DBSCAN cluster, one colour per cluster.\n"
            "- **Small grey points:** noise, i.e. incidents that belong to no cluster.\n"
            "- **Circles:** each cluster's centroid and radius_m.\n"
            "- **Thick black outline:** a candidate hotspot."
        )
        st.markdown("**Candidate hotspot rule**")
        st.markdown(
            f"A cluster with at least **{config.hotspot.min_incidents:,}** incidents (min_incidents). "
            "This is a size rule only; it does not test statistical significance."
        )
        st.caption(f"DBSCAN parameters: eps_m = {config.dbscan.eps_m:g} m, "
                   f"min_samples = {config.dbscan.min_samples:,}.")


def _category_filter(container, frame: pd.DataFrame, column: str, label: str) -> set[str] | None:
    if column not in frame.columns:
        return None
    options = sorted(category_values(frame[column]).unique(), key=lambda v: (v == MISSING_LABEL, v))
    chosen = container.multiselect(label, options, default=options, key=f"f_{column}")
    return set(chosen)


# --- Density page -----------------------------------------------------------------------


def _render_density_page(results: dict[str, Any]) -> None:
    if results["density_error"]:
        st.error(f"KDE did not run: {results['density_error']}")
        return
    density = results["density"]
    p = density.params
    kpi_strip([
        ("Incidents used", f"{p['n_points']:,}"),
        ("Grid cells", f"{density.density.shape[0]} × {density.density.shape[1]}"),
        ("Bandwidth", f"{p['bandwidth_m']:g} m"),
        ("Analysis status", analysis_status(results)),
    ])
    map_col, info_col = st.columns(MAP_PANEL_RATIO, gap="medium")
    with map_col:
        st.caption("KDE surface computed from all accepted incidents, drawn grid cell by grid cell. "
                   "Display filters do not apply here.")
        st_folium(build_density_map(density), height=520, use_container_width=True, returned_objects=[],
                  key="density_map")
    with info_col, st.container(border=True):
        st.markdown("**How to read this map**")
        st.info(KDE_DISCLAIMER, icon=":material/info:")
        st.markdown(
            "- **KDE** spreads each incident over its surroundings with a smooth kernel and adds them up.\n"
            f"- **Bandwidth ({p['bandwidth_m']:g} m):** how far each incident spreads; larger values give a "
            "smoother surface.\n"
            f"- **Grid cell ({p['grid_cell_m']:g} m):** the size of each coloured square.\n"
            "- **Relative scores:** compare cells within this map only."
        )
        st.markdown(
            f"**High-density layer** (switch on in the map's layer control): cells with density ≥ the "
            f"{p['high_density_quantile']:.0%} quantile of this grid. This is relative to this analysis and grid "
            "extent only; it is not statistically significant risk."
        )
    st.markdown(
        f"- **Colour scale:** {DENSITY_LEGEND} {DENSITY_SCALE_NOTE} Cells below {DENSITY_TRANSPARENT_BELOW:.0%} "
        "of the grid maximum are drawn transparent so the basemap stays visible; the values themselves are unchanged.\n"
        "- Values depend on the bandwidth and the grid extent, so they are not comparable across runs with "
        "different settings or data.\n"
        "- Each cell shows the estimate at its centre node; the grid is approximately square and is placed on "
        "the Web Mercator basemap row by row."
    )
    ext = p["grid_extent"]
    params_table = pd.DataFrame(
        [
            ("bandwidth_m", p["bandwidth_m"]), ("kernel", p["kernel"]), ("grid_cell_m", p["grid_cell_m"]),
            ("grid size (rows × columns)", f"{density.density.shape[0]} × {density.density.shape[1]}"),
            ("lat_step_deg", f"{p['lat_step_deg']:.7f}"), ("lon_step_deg", f"{p['lon_step_deg']:.7f}"),
            ("grid extent (S, N, W, E)", f"{ext['south']:.5f}, {ext['north']:.5f}, {ext['west']:.5f}, {ext['east']:.5f}"),
            ("grid source", p["grid_source"]), ("high_density_quantile", p["high_density_quantile"]),
            ("high_density_threshold (relative score)", f"{density.high_density_threshold:.4g}"),
            ("incidents used", p["n_points"]), ("density units", p["density_units"]),
        ],
        columns=["parameter", "value"],
    )
    params_table["value"] = params_table["value"].astype(str)
    st.subheader("Parameters used")
    st.caption(f"Bandwidth {p['bandwidth_m']:g} m · Grid cell {p['grid_cell_m']:g} m · "
               f"Threshold quantile {p['high_density_quantile']:g} · Kernel {p['kernel']} · "
               f"Threshold score {density.high_density_threshold:.4g}")
    with st.expander("All KDE parameters", icon=":material/table_rows:"):
        st.dataframe(params_table, hide_index=True, width="stretch")


# --- Summary page -----------------------------------------------------------------------


def _render_summary_page(dataset: CleanDataset, results: dict[str, Any]) -> None:
    st.caption("Descriptive summary of all accepted incidents. Display filters on the Clusters page do not apply here.")
    if is_synthetic_source(dataset.source_name):
        st.info(SYNTHETIC_NOTICE, icon=":material/science:")
    for key, name in (("cluster_error", "DBSCAN"), ("density_error", "KDE")):
        if results[key]:
            st.warning(f"{name} did not run: {results[key]}")
    if results["summary_error"]:
        st.error(f"Summary failed: {results['summary_error']}")
        return
    s = results["summary"]
    report = dataset.report
    clusters = results["clusters"]
    st.subheader("Overview")
    kpi_grid([
        ("Rows in file", f"{report.total_rows:,}"),
        ("Accepted incidents", f"{s.incident_count:,}"),
        ("Rejected", f"{report.rejected_rows:,}"),
        ("Analysis status", analysis_status(results)),
        ("Clusters", NOT_RUN if s.cluster_count is None else str(s.cluster_count)),
        ("Candidate hotspots", NOT_RUN if s.candidate_hotspot_count is None else str(s.candidate_hotspot_count)),
        ("Noise incidents", NOT_RUN if clusters is None else f"{clusters.noise_count:,} of {s.incident_count:,}"),
        ("Noise share", NOT_RUN if s.noise_share is None else f"{s.noise_share:.1%}"),
    ], SUMMARY_KPI_KEY)
    st.caption(
        f"Bounding box (min lat, min lon, max lat, max lon): {', '.join(f'{v:.5f}' for v in s.bounding_box)} · "
        f"Mean centre (lat, lon): {s.mean_center[0]:.5f}, {s.mean_center[1]:.5f}"
    )
    with st.container(key=f"{SUMMARY_PANEL_PREFIX}save"):
        _render_save_section(dataset, results)

    comparison_tab, distributions_tab, notes_tab = st.tabs(SUMMARY_TABS)
    mc = s.method_comparison
    with comparison_tab:
        _render_method_comparison(mc)
    with distributions_tab:
        _render_distributions(dataset, s)
    with notes_tab, st.container(key=f"{SUMMARY_PANEL_PREFIX}notes"):
        st.subheader("Notes and caveats")
        st.markdown("\n".join(f"- {n}" for n in s.notes + (mc.notes if mc else [])))


def _render_method_comparison(mc) -> None:
    with st.container(key=f"{SUMMARY_PANEL_PREFIX}comparison"):
        st.subheader("DBSCAN vs KDE (descriptive comparison)")
        if mc is None:
            st.info("Not available: the comparison needs both DBSCAN and KDE results.")
            return
        st.dataframe(
            pd.DataFrame(
                {
                    "KDE high density": [mc.clustered_high, mc.noise_high, mc.high_density_eligible],
                    "KDE not high": [mc.clustered_not_high, mc.noise_not_high, mc.not_high_density_eligible],
                    "Total (eligible)": [mc.clustered_eligible, mc.noise_eligible, mc.eligible_count],
                },
                index=["DBSCAN clustered", "DBSCAN noise", "Total (eligible)"],
            ),
            width="stretch",
        )
        st.caption(
            f"Eligible = inside the KDE grid extent ({mc.eligible_count:,} of {mc.total_incidents:,}); "
            f"outside the grid and excluded: {mc.outside_grid_count:,}. "
            f"Clustered at high density: {_share(mc.clustered_high_share)} · "
            f"Noise at high density: {_share(mc.noise_high_share)}."
        )
        if mc.per_cluster:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"cluster": o.cluster_label, "incidents": o.incident_count, "eligible": o.eligible_members,
                         "outside grid": o.outside_grid_members, "at high density": o.members_at_high_density,
                         "share at high density": _share(o.high_density_share),
                         "candidate hotspot (size rule)": "yes" if o.is_candidate_hotspot else "no"}
                        for o in mc.per_cluster
                    ]
                ),
                hide_index=True, width="stretch",
                column_config={
                    "cluster": st.column_config.NumberColumn("Cluster", help="An identifier, not a rank", format="%d"),
                    "incidents": st.column_config.NumberColumn("Incidents", format="%d"),
                    "eligible": st.column_config.NumberColumn("Eligible", format="%d"),
                    "outside grid": st.column_config.NumberColumn("Outside grid", format="%d"),
                    "at high density": st.column_config.NumberColumn("At high density", format="%d"),
                    "share at high density": st.column_config.TextColumn("Share at high density"),
                    "candidate hotspot (size rule)": st.column_config.TextColumn("Candidate hotspot (size rule)"),
                },
            )


def _render_distributions(dataset: CleanDataset, s) -> None:
    st.subheader("Incidents by category and date")
    categories = [(column, title) for column, title in (("severity", "Severity"), ("incident_type", "Incident type"))
                  if s.by_category.get(column)]
    if categories:
        for slot, (column, title) in zip(st.columns(len(categories), gap="small"), categories):
            counts = s.by_category[column]
            with slot:
                _summary_bar_chart(list(counts), list(counts.values()), f"Incidents by {title.lower()}",
                                   "All accepted incidents", title, column)
    if not s.by_category:
        st.caption("No severity or incident_type column in this dataset.")
    timeline = incidents_by_period(dataset)
    if timeline["column_present"] and not timeline["counts"].empty:
        counts = timeline["counts"]
        _summary_bar_chart(counts["period_start"], counts["incident_count"], f"Incidents per {timeline['period']}",
                           "All accepted incidents with a valid date", timeline["period"].capitalize(), "dates")
        if timeline["missing_dates"]:
            st.caption(f"{timeline['missing_dates']:,} incident(s) have no valid date and are not in this chart.")
    elif timeline["column_present"]:
        st.caption("incident_date is present but no incident has a valid ISO 8601 date, so no date chart is shown.")
    else:
        st.caption("No incident_date column in this dataset.")


def _summary_bar_chart(x, y, title: str, subtitle: str, xaxis_title: str, name: str) -> None:
    """One count chart in a white panel; values come straight from the summary."""
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=ACCENT, text=y, textposition="outside", cliponaxis=False))
    fig.update_layout(**bar_chart_layout(title, subtitle, xaxis_title))
    with st.container(key=f"{SUMMARY_PANEL_PREFIX}chart_{name}"):
        # theme=None: Streamlit's chart theme would replace the template's white background.
        st.plotly_chart(fig, width="stretch", theme=None, key=f"chart_{name}")


# --- history (Stage 8) ---------------------------------------------------------------------


def _render_save_section(dataset: CleanDataset, results: dict[str, Any]) -> None:
    """Explicit save of the analysis shown on screen; at most once per analysis run.

    The guard lives in the cache entry, which belongs to exactly one analysis
    (this dataset object + these parameters). New parameters or a new dataset
    create a new entry, so that run can be saved once too.
    """
    st.subheader("Save to history")
    if results["cluster_error"] or results["density_error"] or results["summary"] is None:
        st.caption("Saving is available only when DBSCAN, KDE and the summary all completed.")
        return
    if results.get("saved_run_id"):
        st.success(f"This analysis is saved in the history as run {results['saved_run_id']}.")
    else:
        if not st.button("Save this run to history", key="save_run", type="primary"):
            return
        try:
            run = record_run(dataset, results["config"], results["clusters"], results["density"],
                             results["summary"], db_path=HISTORY_DB_PATH)
        except (sqlite3.Error, OSError, ValueError, AnalysisError) as exc:
            st.error(f"Could not save the run: {exc}")
            return
        results["saved_run_id"] = run.run_id
        results["saved_run"] = run
        st.success(f"Saved to the history as run {run.run_id}.")
    _render_report_section(results)


# --- reports (Stage 9) ---------------------------------------------------------------------


def _render_report_section(results: dict[str, Any]) -> None:
    """Generate reports once for the run saved from this cache entry, then offer downloads."""
    st.subheader("Reports")
    st.warning(CSV_SAFETY_WARNING)
    paths = results.get("report_paths")
    if paths is None:
        if not st.button("Generate reports", key="generate_reports", type="primary"):
            st.caption("Writes incidents.csv, clusters.csv and report.pdf once for this saved run.")
            return
        try:
            paths = generate_reports(results["saved_run"], HISTORY_REPORTS_DIR, db_path=HISTORY_DB_PATH)
        except (sqlite3.Error, OSError, ValueError, LookupError, AnalysisError) as exc:
            st.error(f"Could not generate reports: {exc}")
            return
        results["report_paths"] = paths
        st.success("Reports generated for this run.")
    _download_buttons(paths, "summary")


def _download_buttons(paths: list[Path], key_prefix: str) -> None:
    for path in paths:
        if path.exists():
            st.download_button(
                f"Download {path.name}", data=path.read_bytes(), file_name=path.name,
                mime=REPORT_MIME.get(path.suffix, "application/octet-stream"),
                key=f"{key_prefix}_{path.parent.name}_{path.name}",
            )
        else:
            st.warning(f"Missing file: {path.parent.name}/{path.name} is no longer in the reports folder.")


def _render_history_page() -> None:
    _page_header("History & Reports")
    st.subheader("Saved runs")
    try:
        runs = list_runs(HISTORY_LIMIT, db_path=HISTORY_DB_PATH)
    except (sqlite3.Error, OSError, ValueError) as exc:
        st.error(f"Could not read the run history: {exc}")
        runs = None
    if runs == []:
        st.info("No runs saved yet. Run an analysis and use 'Save this run to history' on the Summary page.")
    elif runs:
        kpi_strip([
            ("Saved runs", f"{len(runs)}{'+' if len(runs) == HISTORY_LIMIT else ''}"),
            ("Runs with reports", str(sum(1 for r in runs if r["report_paths"]))),
        ])
        st.caption(f"Newest first; showing up to {HISTORY_LIMIT}. Times are UTC.")
        st.dataframe(pd.DataFrame([_history_row(r) for r in runs]), hide_index=True, width="stretch")

    st.subheader("Reports")
    st.caption(
        "Reports are generated on the Summary page for a run saved in this session. Runs from earlier "
        "sessions cannot be regenerated, because the history stores parameters, not results; their reports "
        "can be downloaded here only if they were registered and the files still exist."
    )
    st.warning(CSV_SAFETY_WARNING)
    with_reports = [r for r in runs or [] if r["report_paths"]]
    if not with_reports:
        st.info("No reports registered yet.")
        return
    chosen = st.selectbox("Run", [r["run_id"] for r in with_reports], key="history_report_run")
    row = next(r for r in with_reports if r["run_id"] == chosen)
    resolved = []
    for stored in row["report_paths"]:
        try:
            resolved.append(resolve_report_path(stored, HISTORY_REPORTS_DIR))
        except ValueError as exc:
            st.error(f"Invalid stored report path: {exc}")
    _download_buttons(resolved, "history")


def _history_row(run: dict[str, Any]) -> dict[str, Any]:
    c = run["config"]
    usable = run["valid_rows"] > 0
    return {
        "saved (UTC)": run["created_at"].replace("T", " ")[:19],
        "run id": run["run_id"],
        "source": run["source_name"],
        "accepted / total rows": f"{run['valid_rows']:,} / {run['total_rows']:,}",
        "status": "complete" if usable else "unusable dataset (no analysis)",
        "reports": f"{len(run['report_paths'])} file(s)" if run["report_paths"] else "none",
        "clusters": NOT_RUN if run["cluster_count"] is None else run["cluster_count"],
        "candidate hotspots": NOT_RUN if run["candidate_hotspot_count"] is None else run["candidate_hotspot_count"],
        "noise incidents": NOT_RUN if run["noise_count"] is None else run["noise_count"],
        "eps_m": c.dbscan.eps_m, "min_samples": c.dbscan.min_samples, "min_incidents": c.hotspot.min_incidents,
        "bandwidth_m": c.kde.bandwidth_m, "grid_cell_m": c.kde.grid_cell_m,
        "high_density_quantile": c.kde.high_density_quantile,
    }


def _share(value: float | None) -> str:
    return "not defined (no eligible incidents)" if value is None else f"{value:.1%}"


def render_data_page() -> None:
    """Load a CSV (sample or upload), validate it, and show the quality report."""
    _page_header("Data")
    samples = list_sample_datasets()
    with st.container(border=True):
        st.markdown("**Data source**")
        st.caption("Upload a CSV with incident_id, latitude and longitude columns (WGS84 decimal degrees); "
                   "severity, incident_type and incident_date are optional. Or choose a bundled sample dataset.")
        mode = st.radio("Source", ("Upload a CSV", "Sample dataset"), horizontal=True)

        source = None
        if mode == "Sample dataset":
            if not samples:
                st.info("No sample datasets in data/sample yet.")
            else:
                source = st.selectbox("Sample file", samples, format_func=lambda p: p.name)
        else:
            source = st.file_uploader("CSV file", type=["csv"])

    if source is None:
        st.session_state.pop("dataset", None)
        return

    try:
        dataset = load_and_validate(source)
    except DataValidationError as exc:
        st.session_state.pop("dataset", None)
        st.error(f"This file cannot be used: {exc}")
        return

    st.session_state["dataset"] = dataset
    _render_validation(dataset)


def validation_status(report) -> str:
    """Validation status KPI: Ready, Ready with rejections, or Unusable (from the existing report)."""
    if not report.is_usable:
        return "Unusable"
    return "Ready with rejections" if report.rejected_rows else "Ready"


def _render_validation(dataset: CleanDataset) -> None:
    report = dataset.report
    st.subheader("Validation summary")
    st.caption(f"File: {escape_markdown(dataset.source_name)}")
    kpi_strip([
        ("Rows in file", f"{report.total_rows:,}"),
        ("Accepted", f"{report.valid_rows:,}"),
        ("Rejected", f"{report.rejected_rows:,}"),
        ("Validation status", validation_status(report)),
    ])

    if not report.is_usable:
        st.error(
            "No valid rows remain, so this dataset is unusable. "
            "Spatial analysis will not run. Fix the issues below and upload again.",
            icon=":material/error:",
        )
    elif report.rejected_rows:
        st.warning(f"{report.rejected_rows:,} row(s) were rejected and excluded from analysis. "
                   "The dataset is ready for analysis with the accepted rows.", icon=":material/warning:")
    else:
        st.success("All rows passed validation. The dataset is ready for analysis.", icon=":material/check_circle:")

    present = ", ".join(report.optional_columns_present) or "none"
    extra = ", ".join(report.extra_columns_preserved) or "none"
    st.caption(f"Optional columns present: {present}. Extra columns preserved: {extra}.")

    map_tab, issues_tab, preview_tab = st.tabs(
        ["Incident Map", f"Validation Issues ({len(report.issues):,})", "Data Preview"])
    with map_tab:
        _render_incident_map(dataset)
    with issues_tab:
        if report.issues:
            st.caption("Row numbers are 0-based data rows (row 0 = first line after the header).")
            st.dataframe(summarize_quality(report), hide_index=True, width="stretch")
        else:
            st.caption("No validation issues.")
    with preview_tab:
        if report.is_usable:
            st.caption(f"Accepted rows (first {min(PREVIEW_ROWS, report.valid_rows):,} of {report.valid_rows:,}).")
            st.dataframe(dataset.frame.head(PREVIEW_ROWS), width="stretch")
        else:
            st.caption("No accepted rows to preview.")


def _render_incident_map(dataset: CleanDataset) -> None:
    """Base point map of accepted incidents. No clustering or density layers."""
    if not dataset.report.is_usable or dataset.frame.empty:
        st.info("Map not shown: there are no accepted incidents to plot.")
        return
    accepted = len(dataset.frame)
    shown = min(accepted, MAX_MAP_POINTS)
    if shown < accepted:
        st.warning(
            f"Only the first {shown:,} of {accepted:,} accepted incidents (in file order) are displayed "
            "to keep the map responsive. This is NOT a representative sample — the map may not reflect "
            "where incidents are concentrated. All accepted incidents remain in the dataset."
        )
    else:
        st.caption(f"{accepted:,} accepted incident(s). Click a point for details.")
    st_folium(build_incident_map(dataset), height=480, use_container_width=True, returned_objects=[], key="incident_map")
