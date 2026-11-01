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

from config.settings import DB_PATH, DEFAULT_ANALYSIS_CONFIG, OPTIONAL_COLUMNS, REPORTS_DIR, REQUIRED_COLUMNS, AnalysisConfig, CandidateHotspotCriteria, DBSCANParams, KDEParams
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
    DENSITY_COLOUR_NOTE,
    DENSITY_SCALE_NOTE,
    DENSITY_SMOOTHING_NOTE,
    DENSITY_TRANSPARENT_BELOW,
    MAX_MAP_POINTS,
    build_cluster_map,
    build_density_map,
    build_incident_map,
    cluster_color,
)
from modules.spatial_statistics import incidents_by_period
from modules.ui_components import dataset_bar, empty_state, kpi_grid, page_header, page_link, panel
from modules.ui_theme import (
    ACCENT,
    CHART_SECONDARY,
    CLUSTER_KPI_KEY,
    DATA_KPI_KEY,
    DENSITY_KPI_KEY,
    FILTERS_KEY,
    FINDING_PREFIX,
    MOBILE_ONLY_KEY,
    HISTORY_DETAIL_KPI_KEY,
    HISTORY_KPI_KEY,
    SUMMARY_DENSITY_KPI_KEY,
    SUMMARY_FINDINGS_KEY,
    SUMMARY_KPI_KEY,
    SURFACE,
    SUCCESS,
    TEXT_PRIMARY,
    WARNING,
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
MAP_DOMINANT_RATIO = (5, 2)       # the map is the main element of the Clusters and Density pages
DOMINANT_MAP_HEIGHT_PX = 620
SUMMARY_DENSITY_RATIO = (3, 2)
SUMMARY_MAP_HEIGHT_PX = 520
SUMMARY_DENSITY_MAP_HEIGHT_PX = 420
HISTORY_DETAIL_RATIO = (3, 2)
REPORT_NOTICE_KEY = "history_report_notice"     # run id whose reports were generated in the last run
REPORT_STATUS_COLOURS = {"Available": "green", "Ready to generate": "blue", "Not generated": "gray",
                         "Partly available": "orange", "Files missing": "red"}
REPORT_FILES_NOTE = "Writes incidents.csv, clusters.csv and report.pdf once for this saved run."
HISTORY_STORAGE_NOTE = ("The history stores these parameters and totals, not the incident rows or per-cluster "
                        "results. To see the maps again, load the same data and enter these parameters.")
FINDINGS_NOTE = ("These findings describe this dataset with these parameters only. They do not show statistical "
                 "significance or predict future incidents.")

# --- Summary page (Stage 10B Phase 4.3) ---------------------------------------------------
SUMMARY_TABS = ("Method Comparison", "Distributions", "Notes & Limitations")
SYNTHETIC_NOTICE = ("Synthetic demonstration data: every record is artificial. These results show how the "
                    "methods work and are not real-world incident statistics.")

# --- Data page (redesign Stage 2) -----------------------------------------------------------
SOURCE_OPTIONS = ("Upload a CSV", "Sample dataset")
# The uploader and selector are rendered in different places (the workspace, or the
# "Change dataset" expander), so they need stable keys to keep their value.
SOURCE_MODE_KEY = "data_source_mode"
SOURCE_UPLOAD_KEY = "data_upload"
SOURCE_SAMPLE_KEY = "data_sample"
DATASET_KEY = "dataset"
INCIDENT_MAP_HEIGHT_PX = 560

# --- tables, empty states and History (Stage 10B Phase 4.4) -------------------------------
TABLE_SCROLL_HINT = "On narrow screens, scroll this table sideways to see every column."
# The History frame keeps every column; these lists only choose what each table displays.
# Run ID sits with the parameters so the results table fits a laptop without sideways scrolling.
HISTORY_RESULT_COLUMNS = ("analysis id", "source", "saved (UTC)", "accepted / total rows", "clusters",
                          "candidate hotspots", "noise incidents", "status", "actions", "reports")
HISTORY_PARAMETER_COLUMNS = ("saved (UTC)", "run id", "eps_m", "min_samples", "min_incidents", "bandwidth_m",
                             "grid_cell_m", "high_density_quantile")

# --- application shell (Stage 10B Phase 2) ---------------------------------------------
BRAND_NAME = "Hotspot Analytics"
BRAND_TAGLINE = "Spatial Incident Analysis"
# Page name (as used by render_page and the tests) -> navigation label, Material icon,
# URL path and the one-line description shown under the page title.
PAGE_INFO: dict[str, tuple[str, str, str, str]] = {
    "Data": ("Data", ":material/upload_file:", "data", "Import and validate incident datasets."),
    "Clusters (DBSCAN)": ("Clusters", ":material/hub:", "clusters", "Discover spatial clusters using DBSCAN."),
    "Density (KDE)": ("Density", ":material/blur_on:", "density", "Explore relative spatial density using KDE."),
    "Summary": ("Summary", ":material/insights:", "summary",
                "A summary of the current completed spatial analysis: where incidents gather, and how the methods compare."),
    "History & Reports": ("History & Reports", ":material/history:", "history",
                          "Revisit saved spatial analyses and access their reports."),
}


# Where the title differs from the page name.
PAGE_HEADINGS = {"Summary": "Spatial Analysis Overview", "History & Reports": "Analysis History & Reports"}


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

    config = _sidebar_config(expanded=name == "Density (KDE)")     # bandwidth is this page's main control
    _page_header(name)
    dataset = st.session_state.get(DATASET_KEY)
    if dataset is None:
        empty_state("no_dataset", ":material/upload_file:", "No dataset loaded yet",
                    "No dataset loaded. Load and validate a CSV on the Data page first.", link=("Data", "Go to Data"))
        return
    if not dataset.report.is_usable:
        empty_state("unusable_dataset", ":material/report:", "This dataset cannot be analysed",
                    "The loaded dataset is unusable (no accepted incidents), so no analysis runs. Fix it on the Data page.",
                    show=st.warning, link=("Data", "Go to Data"))
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
    page_header(PAGE_HEADINGS.get(name, name), PAGE_INFO[name][3])


def column_label(name: str) -> str:
    """Readable Title Case heading for a data column, e.g. incident_id -> Incident ID."""
    return " ".join("ID" if word == "id" else word.capitalize() for word in str(name).replace("_", " ").split())


def _render_dataset_status(box) -> None:
    """Sidebar summary of the current dataset and last analysis (session state only)."""
    dataset = st.session_state.get(DATASET_KEY)
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


def cluster_view(
    frame: pd.DataFrame,
    severities: set[str] | None,
    incident_types: set[str] | None,
    show_noise: bool,
    chosen: set[int],
    candidates: set[int],
    candidates_only: bool,
) -> tuple[np.ndarray, set[int] | None]:
    """Display mask plus the clusters to draw (None = all). Display-only.

    `chosen` narrows the clusters without affecting noise, which keeps its own switch.
    "Candidate hotspots only" keeps its existing meaning and shows no noise.
    """
    all_clusters = {int(v) for v in frame[CLUSTER_LABEL_COLUMN].unique() if v != NOISE_LABEL}
    if candidates_only:
        visible = chosen & candidates
        return display_mask(frame, severities, incident_types, show_noise, visible), visible
    mask = display_mask(frame, severities, incident_types, show_noise)
    if chosen >= all_clusters:
        return mask, None
    labels = frame[CLUSTER_LABEL_COLUMN].to_numpy()
    return mask & (np.isin(labels, list(chosen)) | (labels == NOISE_LABEL)), chosen


def cluster_rows_html(clusters: ClusterResult, centres: bool = False) -> str:
    """One row per cluster. Built from colours and numbers only, so no text needs escaping.

    centres=True adds each reported centre and a bar drawn from the incident count.
    """
    rows = []
    largest = max((c.incident_count for c in clusters.clusters), default=1)
    for c in clusters.clusters:
        badge = "<em>Candidate hotspot</em>" if c.is_candidate_hotspot else ""
        centre = ""
        if centres:
            bar = f'width: {c.incident_count / largest:.0%}; background: {cluster_color(c.cluster_label)}'
            centre = f'<small>Centre {c.centroid_lat:.5f}, {c.centroid_lon:.5f}</small><u style="{bar}"></u>'
        rows.append(f'<div class="hs-cluster"><i style="background: {cluster_color(c.cluster_label)}"></i>'
                    f"<b>Cluster {c.cluster_label}</b><span>{c.incident_count:,} incidents · {c.radius_m:,.0f} m radius</span>"
                    f"{badge}{centre}</div>")
    return "".join(rows)


def analysis_cache_key(config: AnalysisConfig) -> tuple:
    """Hashable key of every parameter that affects DBSCAN, KDE or the summary."""
    return tuple(sorted((k, repr(v)) for k, v in asdict(config).items()))


def is_synthetic_source(name: str) -> bool:
    """True for files named as synthetic (data/sample/README.md requires it in the file name)."""
    return "synthetic" in name.lower()


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


def _sidebar_config(expanded: bool = False) -> AnalysisConfig | None:
    """Analysis parameters from the sidebar; defaults from config; validated by the dataclasses."""
    d = DEFAULT_ANALYSIS_CONFIG
    sb = st.sidebar.expander("Analysis parameters", expanded=expanded, icon=":material/tune:")
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
        kpi_grid([("Clusters", NOT_RUN), ("Candidate hotspots", NOT_RUN), ("Noise incidents", NOT_RUN),
                  ("Noise share", NOT_RUN)], CLUSTER_KPI_KEY)
        st.error(f"DBSCAN failed: {results['cluster_error']}")
        return
    clusters: ClusterResult = results["clusters"]
    frame = clusters.labeled_frame
    candidates = {c.cluster_label for c in clusters.clusters if c.is_candidate_hotspot}
    summary = results["summary"]
    noise_share = NOT_RUN if summary is None or summary.noise_share is None else f"{summary.noise_share:.1%}"

    kpi_grid([
        ("Clusters", str(len(clusters.clusters))),
        ("Candidate hotspots", str(len(candidates))),
        ("Noise incidents", f"{clusters.noise_count:,} of {len(frame):,}"),
        ("Noise share", noise_share),
    ], CLUSTER_KPI_KEY)

    filters = st.sidebar.container(key=FILTERS_KEY).expander(FILTERS_LABEL, expanded=True, icon=":material/filter_alt:")
    filters.caption("Change only what the cluster map and the 'shown' bars display. "
                    "DBSCAN, KDE and the summary always use all accepted incidents.")
    severities = _category_filter(filters, frame, "severity", "Severity (display only)")
    types = _category_filter(filters, frame, "incident_type", "Incident type (display only)")
    show_noise = filters.checkbox("Show noise points", value=True, key="f_show_noise")
    candidates_only = filters.checkbox("Candidate hotspots only", value=False, key="f_candidates_only")

    map_col, info_col = st.columns(MAP_DOMINANT_RATIO, gap="small")
    with info_col:                                 # drawn first: its selector decides what the map shows
        chosen = _render_cluster_panel(clusters, results["config"])
    mask, visible = cluster_view(frame, severities, types, show_noise, chosen, candidates, candidates_only)
    shown = int(mask.sum())
    with map_col:
        with st.container(key=MOBILE_ONLY_KEY):
            st.caption("Severity, type and noise filters are in the side menu: open it with » at the top left.")
        if shown > MAX_MAP_POINTS:
            st.warning(
                f"Only the first {MAX_MAP_POINTS:,} of {shown:,} selected incidents (in file order) are drawn as points. "
                "This is NOT a representative sample. Every cluster circle is still drawn."
            )
        else:
            st.caption(f"Showing {shown:,} of {len(frame):,} accepted incidents under the current display filters.")
        st_folium(
            build_cluster_map(clusters, MAX_MAP_POINTS, mask, visible),
            height=DOMINANT_MAP_HEIGHT_PX, use_container_width=True, returned_objects=[], key="cluster_map",
        )

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
                "shown under filters": st.column_config.NumberColumn("Shown Under Filters", format="%d"),
                "centroid lat": st.column_config.NumberColumn("Centroid Lat", format="%.6f"),
                "centroid lon": st.column_config.NumberColumn("Centroid Lon", format="%.6f"),
                "radius_m": st.column_config.NumberColumn("Radius (m)", format="%.1f"),
                "candidate hotspot (size rule)": st.column_config.TextColumn("Candidate Hotspot (Size Rule)"),
            },
        )
        st.caption(TABLE_SCROLL_HINT)
    with chart_tab:
        fig = go.Figure(
            [
                go.Bar(name="All members (analysis)", x=table["cluster"].astype(str), y=table["incidents"],
                       marker_color=[cluster_color(c) for c in table["cluster"]],
                       marker_line_color=[TEXT_PRIMARY if c in candidates else "rgba(0,0,0,0)" for c in table["cluster"]],
                       marker_line_width=3),
                go.Bar(name="Shown under display filters", x=table["cluster"].astype(str), y=table["shown under filters"],
                       marker_color=CHART_SECONDARY),
            ]
        )
        # Short wrapped title, legend below the plot and automargins so nothing is
        # clipped or overlapped at phone width; data and bar colours are unchanged.
        fig.update_layout(template=plotly_template(), barmode="group",
                          title={"text": "Cluster sizes<br><sup>White outline = candidate hotspot (size rule only)</sup>",
                                 "x": 0, "xanchor": "left", "y": 0.97, "yanchor": "top"},
                          paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
                          xaxis_title="Cluster label (an identifier, not a rank)", yaxis_title="Incidents",
                          legend={"orientation": "h", "x": 0, "xanchor": "left", "y": -0.3, "yanchor": "top"},
                          margin={"l": 48, "r": 16, "t": 64, "b": 96}, height=400)
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True)
        st.plotly_chart(fig, width="stretch", theme=None, key="chart_cluster_sizes")


def _render_cluster_panel(clusters: ClusterResult, config: AnalysisConfig) -> set[int]:
    """Cluster selector, per-cluster facts and method notes; returns the chosen cluster labels."""
    labels = [c.cluster_label for c in clusters.clusters]
    with panel("cluster_info"):
        st.markdown("#### :material/hub: Clusters")
        chosen = labels
        if labels:
            # The key includes the count so a new parameter result starts with every cluster shown.
            chosen = st.pills("Show on map (display only)", labels, selection_mode="multi", default=labels,
                              format_func=lambda label: f"Cluster {label}", key=f"f_clusters_{len(labels)}")
            st.html(cluster_rows_html(clusters))
        else:
            st.caption("No clusters with these parameters.")
        _cluster_explanation(config)
    return set(chosen)


def _cluster_explanation(config: AnalysisConfig) -> None:
    """Legend and method notes for the cluster map, using this run's parameters."""
    with st.expander("How to read this map", icon=":material/help:"):
        st.markdown(
            "- **Coloured points:** members of a DBSCAN cluster, one colour per cluster.\n"
            "- **Small light-grey points:** noise, i.e. incidents that belong to no cluster.\n"
            "- **Circles:** each cluster's centroid and radius_m.\n"
            "- **Labels:** each cluster's identifier and size.\n"
            "- **Thick white outline:** a candidate hotspot."
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


def _density_controls_hint() -> None:
    with st.container(key=MOBILE_ONLY_KEY):
        st.caption("Bandwidth and the other parameters are in the side menu: open it with » at the top left.")


def _render_density_page(results: dict[str, Any]) -> None:
    if results["density_error"]:
        st.error(f"KDE did not run: {results['density_error']}")
        _density_controls_hint()
        return
    density = results["density"]
    p = density.params
    kpi_grid([
        ("Incidents used", f"{p['n_points']:,}"),
        ("Grid cells", f"{density.density.shape[0]} × {density.density.shape[1]}"),
        ("Bandwidth", f"{p['bandwidth_m']:g} m"),
        ("Analysis status", analysis_status(results)),
        ("Peak relative score", f"{density.density.max():.4g}"),   # the widest value; gets its own row on phones
    ], DENSITY_KPI_KEY)
    map_col, info_col = st.columns(MAP_DOMINANT_RATIO, gap="small")
    with map_col:
        st_folium(build_density_map(density), height=DOMINANT_MAP_HEIGHT_PX, use_container_width=True,
                  returned_objects=[], key="density_map")
        _density_controls_hint()
        st.caption(f"KDE surface computed from all accepted incidents. {DENSITY_SMOOTHING_NOTE} "
                   "Display filters do not apply here.")
    with info_col, panel("density_info"):
        st.markdown("#### :material/blur_on: Reading this map")
        st.info(KDE_DISCLAIMER, icon=":material/info:")
        st.markdown(
            "- **What it shows:** KDE spreads each incident over its surroundings with a smooth kernel and adds "
            "them up, so colour shows where incidents concentrate.\n"
            "- **High areas:** more incidents lie close together there, compared with the rest of this map."
        )
        st.markdown(
            "**Density and DBSCAN clusters differ.** KDE gives a continuous surface with no boundaries or noise. "
            "DBSCAN sorts incidents into separate clusters. A hot area here is not automatically a cluster."
        )
        st.markdown(
            f"**High-density layer** (switch on in the map's layer control): cells with density ≥ the "
            f"{p['high_density_quantile']:.0%} quantile of this grid. This is relative to this analysis and grid "
            "extent only; it is not statistically significant risk."
        )
        with st.expander("More about this map", icon=":material/help:"):
            st.markdown(
                f"- **Colour scale:** {DENSITY_LEGEND} {DENSITY_SCALE_NOTE} {DENSITY_COLOUR_NOTE} Cells below "
                f"{DENSITY_TRANSPARENT_BELOW:.0%} of the grid maximum are drawn transparent so the basemap stays visible; "
                "the values themselves are unchanged.\n"
                f"- **Bandwidth ({p['bandwidth_m']:g} m):** how far each incident spreads; larger values give a smoother surface.\n"
                f"- **Grid cell ({p['grid_cell_m']:g} m):** the spacing of the estimates behind the smoothed surface.\n"
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
        st.dataframe(params_table, hide_index=True, width="stretch",
                     column_config={"parameter": "Parameter", "value": "Value"})


# --- Summary page -----------------------------------------------------------------------


def _count(number: int, noun: str) -> str:
    return f"{number:,} {noun}" if number == 1 else f"{number:,} {noun}s"


def key_findings(dataset: CleanDataset, results: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(icon, title, sentence) for each finding the finished analysis supports.

    Every number is read from the validation report, ClusterResult, DensityResult,
    SpatialSummary or the parameters used. A failed analysis simply adds no finding.
    Numbers and fixed text only, so nothing needs escaping.
    """
    report = dataset.report
    clusters: ClusterResult | None = results["clusters"]
    density = results["density"]
    summary = results["summary"]
    findings = [(":material/fact_check:", "Data analysed",
                 f"{report.valid_rows:,} of {report.total_rows:,} rows were accepted and analysed; "
                 f"{report.rejected_rows:,} rejected.")]
    if clusters is not None:
        found = clusters.clusters
        if found:
            largest = max(found, key=lambda c: c.incident_count)
            clustered = sum(c.incident_count for c in found)
            text = (f"DBSCAN found {_count(len(found), 'cluster')} holding {clustered:,} of {report.valid_rows:,} incidents. "
                    f"The largest is Cluster {largest.cluster_label}, with {largest.incident_count:,} incidents.")
        else:
            text = "DBSCAN found no clusters with these parameters; every incident is noise."
        findings.append((":material/hub:", "Clusters", text))
        share = "" if summary is None or summary.noise_share is None else f" ({summary.noise_share:.1%})"
        findings.append((":material/scatter_plot:", "Noise",
                         f"{clusters.noise_count:,} of {report.valid_rows:,} incidents{share} are noise: with these "
                         "parameters, DBSCAN did not place them in any cluster."))
        candidates = [c.cluster_label for c in found if c.is_candidate_hotspot]
        rule = f"the size rule of at least {results['config'].hotspot.min_incidents:,} incidents"
        if candidates:
            names = ", ".join(f"Cluster {label}" for label in candidates)
            text = (f"{_count(len(candidates), 'cluster')} met {rule}: {names}. "
                    "This is a size rule, not a measure of significance.")
        else:
            text = f"No cluster met {rule}."
        findings.append((":material/location_on:", "Candidate hotspots", text))
    if density is not None:
        row, col = np.unravel_index(int(np.argmax(density.density)), density.density.shape)
        findings.append((":material/blur_on:", "Density peak",
                         f"The highest relative density score, {density.density.max():.4g}, is near "
                         f"{density.grid_lat[row]:.5f}, {density.grid_lon[col]:.5f}. "
                         "Scores compare locations on this map only."))
    comparison = summary.method_comparison if summary is not None else None
    if comparison is not None:
        quantile = density.params["high_density_quantile"]
        text = (f"{comparison.clustered_high:,} of {comparison.clustered_eligible:,} clustered incidents and "
                f"{comparison.noise_high:,} of {comparison.noise_eligible:,} noise incidents lie in high-density cells "
                f"(at or above the {quantile:.0%} quantile of this grid).")
        if comparison.outside_grid_count:
            text += f" {comparison.outside_grid_count:,} incidents outside the grid are not counted."
        findings.append((":material/compare_arrows:", "DBSCAN and KDE", text))
    return findings


def _render_summary_page(dataset: CleanDataset, results: dict[str, Any]) -> None:
    _render_dataset_bar(dataset, analysis_status(results))
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
    clusters = results["clusters"]
    kpi_grid([
        ("Accepted incidents", f"{s.incident_count:,} of {dataset.report.total_rows:,}"),
        ("Rejected", f"{dataset.report.rejected_rows:,}"),
        ("Clusters", NOT_RUN if s.cluster_count is None else str(s.cluster_count)),
        ("Candidate hotspots", NOT_RUN if s.candidate_hotspot_count is None else str(s.candidate_hotspot_count)),
        ("Noise incidents", NOT_RUN if clusters is None else f"{clusters.noise_count:,}"),
        ("Noise share", NOT_RUN if s.noise_share is None else f"{s.noise_share:.1%}"),
    ], SUMMARY_KPI_KEY)
    _render_geographic_overview(results)
    _render_density_overview(results)
    _render_key_findings(dataset, results)
    with panel("save"):
        _render_save_section(dataset, results)

    comparison_tab, distributions_tab, notes_tab = st.tabs(SUMMARY_TABS)
    mc = s.method_comparison
    with comparison_tab:
        _render_method_comparison(mc)
    with distributions_tab:
        _render_distributions(dataset, s)
    with notes_tab, panel("notes"):
        st.subheader("Notes and caveats")
        st.markdown("\n".join(f"- {n}" for n in s.notes + (mc.notes if mc else [])))


def _render_geographic_overview(results: dict[str, Any]) -> None:
    """The existing cluster map and the existing cluster facts, side by side."""
    clusters: ClusterResult | None = results["clusters"]
    map_col, info_col = st.columns(MAP_DOMINANT_RATIO, gap="small")
    with map_col, panel("geographic_overview", height="stretch"):
        st.subheader("Geographic overview")
        if clusters is None:
            st.info("Not available: the map needs a DBSCAN result.")
        else:
            shown = len(clusters.labeled_frame)
            if shown > MAX_MAP_POINTS:
                st.warning(
                    f"Only the first {MAX_MAP_POINTS:,} of {shown:,} accepted incidents (in file order) are drawn as "
                    "points. This is NOT a representative sample. Every cluster circle is still drawn."
                )
            st_folium(build_cluster_map(clusters), height=SUMMARY_MAP_HEIGHT_PX, use_container_width=True,
                      returned_objects=[], key="summary_cluster_map")
        s = results["summary"]
        st.caption(
            f"Bounding box (min lat, min lon, max lat, max lon): {', '.join(f'{v:.5f}' for v in s.bounding_box)} · "
            f"Mean centre (lat, lon): {s.mean_center[0]:.5f}, {s.mean_center[1]:.5f}"
        )
    with info_col, panel("cluster_overview", height="stretch"):
        st.subheader("Cluster analysis")
        if clusters is None:
            st.info("Not available: this section needs a DBSCAN result.")
        elif clusters.clusters:
            st.html(f'<div class="hs-cluster-list">{cluster_rows_html(clusters, centres=True)}</div>')
            st.caption("Cluster numbers are identifiers, not ranks. Radius is the farthest member from the centre. "
                       "Bars show incident counts relative to the largest cluster.")
        else:
            st.caption("No clusters with these parameters.")
        page_link("Clusters (DBSCAN)", "Open Clusters")


def _render_density_overview(results: dict[str, Any]) -> None:
    """The existing KDE map and values; nothing is re-estimated here."""
    density = results["density"]
    if density is None:
        with panel("density_overview"):
            st.subheader("Density analysis")
            st.info("Not available: this section needs a KDE result.")
        return
    map_col, info_col = st.columns(SUMMARY_DENSITY_RATIO, gap="small")
    with map_col, panel("density_overview", height="stretch"):
        st.subheader("Density analysis")
        st_folium(build_density_map(density), height=SUMMARY_DENSITY_MAP_HEIGHT_PX, use_container_width=True,
                  returned_objects=[], key="summary_density_map")
    with info_col, panel("density_facts", height="stretch"):
        st.markdown("#### :material/blur_on: KDE results")
        kpi_grid([
            ("Grid cells", f"{density.density.shape[0]} × {density.density.shape[1]}"),
            ("Bandwidth", f"{density.params['bandwidth_m']:g} m"),
            ("Peak relative score", f"{density.density.max():.4g}"),
        ], SUMMARY_DENSITY_KPI_KEY)
        st.info(KDE_DISCLAIMER, icon=":material/info:")
        st.caption(f"{DENSITY_SMOOTHING_NOTE} A hot area is not automatically a DBSCAN cluster.")
        page_link("Density (KDE)", "Open Density")


def _render_key_findings(dataset: CleanDataset, results: dict[str, Any]) -> None:
    with panel("key_findings"):
        st.subheader("Key findings")
        with st.container(horizontal=True, wrap=True, key=SUMMARY_FINDINGS_KEY):
            for index, (icon, title, text) in enumerate(key_findings(dataset, results)):
                with st.container(key=f"{FINDING_PREFIX}{index}"):
                    st.markdown(f"**{icon} {title}**")
                    st.markdown(text)
        st.caption(FINDINGS_NOTE)


def _render_method_comparison(mc) -> None:
    with panel("comparison"):
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
            column_config={"_index": "DBSCAN Result", "KDE high density": "KDE High Density",
                           "KDE not high": "KDE Not High", "Total (eligible)": "Total (Eligible)"},
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
                    "outside grid": st.column_config.NumberColumn("Outside Grid", format="%d"),
                    "at high density": st.column_config.NumberColumn("At High Density", format="%d"),
                    "share at high density": st.column_config.TextColumn("Share at High Density", alignment="right"),
                    "candidate hotspot (size rule)": st.column_config.TextColumn("Candidate Hotspot (Size Rule)"),
                },
            )
            st.caption(TABLE_SCROLL_HINT)


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
    with panel(f"chart_{name}"):
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
        slot = st.empty()                          # lets the button go as soon as it has done its job
        if not slot.button("Save this run to history", key="save_run", type="primary"):
            return
        try:
            run = record_run(dataset, results["config"], results["clusters"], results["density"],
                             results["summary"], db_path=HISTORY_DB_PATH)
        except (sqlite3.Error, OSError, ValueError, AnalysisError) as exc:
            st.error(f"Could not save the run: {exc}")
            return
        slot.empty()
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
        if not _report_button(results, "generate_reports"):
            return
        paths = results["report_paths"]
        st.success("Reports generated for this run.")
    _download_buttons(paths, "summary")


def _report_button(results: dict[str, Any], key: str) -> bool:
    """Generate reports for the run saved from this cache entry; True once they exist.

    On failure the button stays so the user can retry. generate_reports leaves
    nothing behind after a failure.
    """
    slot = st.empty()                              # lets the button go as soon as it has done its job
    if not slot.button("Generate reports", key=key, type="primary"):
        st.caption(REPORT_FILES_NOTE)
        return False
    try:
        with st.spinner("Generating reports…"):
            paths = generate_reports(results["saved_run"], HISTORY_REPORTS_DIR, db_path=HISTORY_DB_PATH)
    except (sqlite3.Error, OSError, ValueError, LookupError, AnalysisError) as exc:
        st.error(f"Could not generate reports: {exc}")
        st.caption("No reports were saved for this attempt. Fix the problem above, then try again.")
        return False
    slot.empty()
    results["report_paths"] = paths
    return True


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
    try:
        runs = list_runs(HISTORY_LIMIT, db_path=HISTORY_DB_PATH)
    except (sqlite3.Error, OSError, ValueError) as exc:
        st.error(f"Could not read the run history: {exc}")
        return
    if not runs:
        empty_state("no_runs", ":material/history:", "No saved analyses yet",
                    "No runs saved yet. Run an analysis and use 'Save this run to history' on the Summary page.",
                    link=("Summary", "Go to Summary"))
        return
    files = {r["run_id"]: _report_files(r)[0] for r in runs}
    available = sum(path.exists() for paths in files.values() for path in paths)
    more = "+" if len(runs) == HISTORY_LIMIT else ""
    kpi_grid([
        ("Saved analyses", f"{len(runs)}{more}"),
        ("Latest analysis (UTC)", runs[0]["created_at"][:10]),
        ("Analyses with reports", f"{sum(1 for r in runs if r['report_paths'])}{more}"),
        ("Report files available", f"{available}{more}"),
    ], HISTORY_KPI_KEY)

    table = pd.DataFrame([_history_row(r, _history_actions(r, files[r["run_id"]])) for r in runs])
    with panel("runs"):
        st.subheader("Saved analyses")
        st.caption(f"Newest first; showing up to {HISTORY_LIMIT}. Times are UTC.")
        st.dataframe(table.style.map(_history_cell_colour), hide_index=True, width="stretch",
                     column_order=HISTORY_RESULT_COLUMNS, column_config=_history_column_config())
        st.caption(TABLE_SCROLL_HINT)
        with st.expander("Analysis parameters for each run", icon=":material/tune:"):
            st.dataframe(table, hide_index=True, width="stretch", column_order=HISTORY_PARAMETER_COLUMNS,
                         column_config=_history_column_config())
        labels = {r["run_id"]: _run_label(r) for r in runs}
        chosen = st.selectbox("Saved analysis", list(labels), index=None, format_func=labels.get,
                              placeholder="Choose a saved analysis", key="history_report_run")
    if chosen is None:
        empty_state("no_selection", ":material/touch_app:", "No analysis selected",
                    "Choose a saved analysis above to see its details and reports.")
        return
    run = next(r for r in runs if r["run_id"] == chosen)
    details_col, reports_col = st.columns(HISTORY_DETAIL_RATIO, gap="small")
    with details_col, panel("run_details", height="stretch"):
        _render_run_details(run)
    with reports_col, panel("run_reports", height="stretch"):
        _render_run_reports(run)


def _render_run_details(run: dict[str, Any]) -> None:
    """Everything the history stored for one run. Nothing is re-analysed."""
    c = run["config"]
    row = _history_row(run)
    st.subheader(f"Analysis {run['run_id'][:8]}")
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(f":material/description: **{escape_markdown(run['source_name'])}**", width="content")
        st.badge(row["status"].capitalize(), color="green" if run["valid_rows"] > 0 else "orange")
    st.caption(f"Saved {row['saved (UTC)']} UTC · Run ID {run['run_id']}")
    if is_synthetic_source(run["source_name"]):
        st.info(SYNTHETIC_NOTICE, icon=":material/science:")
    kpi_grid([
        ("Rows in file", f"{run['total_rows']:,}"),
        ("Accepted", f"{run['valid_rows']:,}"),
        ("Rejected", f"{run['total_rows'] - run['valid_rows']:,}"),
        ("Clusters", str(row["clusters"])),
        ("Candidate hotspots", str(row["candidate hotspots"])),
        ("Noise incidents", str(row["noise incidents"])),
    ], HISTORY_DETAIL_KPI_KEY)
    dbscan_col, kde_col = st.columns(2, gap="small")
    with dbscan_col:
        st.markdown("**DBSCAN parameters**")
        st.markdown(f"- Eps: {c.dbscan.eps_m:g} m\n- Min samples: {c.dbscan.min_samples}\n"
                    f"- Candidate hotspot size: at least {c.hotspot.min_incidents:,} incidents")
    with kde_col:
        st.markdown("**KDE parameters**")
        st.markdown(f"- Bandwidth: {c.kde.bandwidth_m:g} m\n- Kernel: {c.kde.kernel}\n"
                    f"- Grid cell: {c.kde.grid_cell_m:g} m\n- High-density quantile: {c.kde.high_density_quantile:g}")
    if c.study_area is not None:
        st.caption(f"Study area: {escape_markdown(c.study_area.name)}")
    st.caption(HISTORY_STORAGE_NOTE)


def _render_run_reports(run: dict[str, Any]) -> None:
    """The reports of one run; generating here uses the same step as the Summary page."""
    st.subheader("Reports")
    entry = _session_entry(run)
    resolved, errors = _report_files(run)
    status = report_status(run, resolved, entry is not None)
    st.badge(status, color=REPORT_STATUS_COLOURS[status])
    if st.session_state.pop(REPORT_NOTICE_KEY, None) == run["run_id"]:
        st.success("Reports generated for this run.")
    for message in errors:
        st.error(message)
    if run["report_paths"]:
        st.warning(CSV_SAFETY_WARNING)
        with st.container(horizontal=True, wrap=True):
            _download_buttons(resolved, "history")
    elif entry is not None:
        if _report_button(entry, "history_generate_reports"):
            st.session_state[REPORT_NOTICE_KEY] = run["run_id"]
            st.rerun()                                     # the table and KPIs above need the new reports
    else:
        empty_state("no_reports", ":material/description:", "No reports for this analysis",
                    "No reports registered yet. To get them, run the same data and parameters on the Summary page, "
                    "save that run, then choose Generate reports.",
                    link=("Summary", "Go to Summary"))
    st.caption(
        "Reports can be generated only while a saved run's results are still in this session, which ends "
        "when the parameters or dataset change. Other runs cannot be regenerated, because the history "
        "stores parameters, not results; their reports can be downloaded here only if they were "
        "registered and the files still exist."
    )


def _report_files(run: dict[str, Any]) -> tuple[list[Path], list[str]]:
    """Absolute paths of a run's registered reports, plus a message for each invalid stored path."""
    resolved, errors = [], []
    for stored in run["report_paths"] or []:
        try:
            resolved.append(resolve_report_path(stored, HISTORY_REPORTS_DIR))
        except ValueError as exc:
            errors.append(f"Invalid stored report path: {exc}")
    return resolved, errors


def _session_entry(run: dict[str, Any]) -> dict[str, Any] | None:
    """The cached analysis behind a run saved in this session; only that one can still make reports."""
    cached = st.session_state.get(CACHE_KEY)
    if cached is None or cached.get("saved_run_id") != run["run_id"]:
        return None
    return cached


def report_status(run: dict[str, Any], files: list[Path], can_generate: bool) -> str:
    """Report state from what is really registered and on disk."""
    registered = len(run["report_paths"] or [])
    if not registered:
        return "Ready to generate" if can_generate else "Not generated"
    present = sum(path.exists() for path in files)
    if present == registered:
        return "Available"
    return "Partly available" if present else "Files missing"


def _history_actions(run: dict[str, Any], files: list[Path]) -> str:
    if any(path.exists() for path in files):
        return "View, download"
    if not run["report_paths"] and _session_entry(run) is not None:
        return "View, generate"
    return "View"


def _history_cell_colour(value: Any) -> str:
    """Status colour for the runs table; the text itself always states the status."""
    if value == "complete":
        return f"color: {SUCCESS}"
    if isinstance(value, str) and value.startswith("unusable"):
        return f"color: {WARNING}"
    return ""


def _run_label(run: dict[str, Any]) -> str:
    """Readable name for a saved run: saved time, source file and short run id."""
    return f"{run['created_at'].replace('T', ' ')[:16]} UTC · {run['source_name']} · {run['run_id'][:8]}"


def _history_column_config() -> dict[str, Any]:
    """Readable headings for the History tables; counts are right-aligned, text left."""
    text, number = st.column_config.TextColumn, st.column_config.NumberColumn
    return {
        "saved (UTC)": text("Saved (UTC)", width=136),
        "analysis id": text("Analysis ID", width=84, help="The start of the run ID; the full ID is in the details"),
        "actions": text("Actions", width=110, help="View: choose this analysis below to see its details"),
        "run id": text("Run ID", width=90, help="Select the cell to read the full ID"),
        "source": text("Source", width=128),
        "accepted / total rows": text("Accepted", width=76, alignment="right",
                                      help="Accepted rows out of all rows in the file"),
        "status": text("Status", width=78),
        "reports": text("Reports", width=70),
        "clusters": text("Clusters", width=60, alignment="right"),
        "candidate hotspots": text("Cand. Hotspots", width=98, alignment="right", help="Candidate hotspots (size rule)"),
        "noise incidents": text("Noise", width=50, alignment="right", help="Noise incidents"),
        "eps_m": number("Eps (m)"),
        "min_samples": number("Min Samples"),
        "min_incidents": number("Min Incidents"),
        "bandwidth_m": number("Bandwidth (m)"),
        "grid_cell_m": number("Grid Cell (m)"),
        "high_density_quantile": number("Quantile", help="KDE high-density quantile"),
    }


def _history_row(run: dict[str, Any], actions: str = "View") -> dict[str, Any]:
    c = run["config"]
    usable = run["valid_rows"] > 0
    return {
        "saved (UTC)": run["created_at"].replace("T", " ")[:19],
        "analysis id": run["run_id"][:8],
        "actions": actions,
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
    source = _selected_source(samples)
    dataset, load_error = None, None
    if source is not None:
        try:
            dataset = load_and_validate(source)
        except DataValidationError as exc:
            load_error = str(exc)

    # Only a usable file may replace a usable dataset. An empty uploader says nothing about
    # the user's intent: Streamlit forgets it on other pages and empties it while swapping files.
    current = st.session_state.get(DATASET_KEY)
    refused = None
    if dataset is not None and not dataset.report.is_usable and current is not None and current.report.is_usable:
        dataset, refused = None, dataset
    if dataset is not None:
        st.session_state[DATASET_KEY] = dataset
    else:
        dataset = current

    if dataset is None:
        _render_upload_workspace(samples, load_error)
        return

    _render_dataset_bar(dataset)
    if load_error is not None:
        st.error(f"This file cannot be used: {load_error} The current dataset is still loaded.")
    if refused is not None:
        _render_refused_file(refused)
    expanded = load_error is not None or refused is not None or not dataset.report.is_usable
    with st.expander("Change dataset", expanded=expanded, icon=":material/swap_horiz:"):
        _source_controls(samples)
        if st.session_state.get(SOURCE_UPLOAD_KEY) is None:
            st.button("Remove dataset", key="remove_dataset", icon=":material/delete:", on_click=_remove_dataset)
    _render_validation(dataset)


def _render_refused_file(refused: CleanDataset) -> None:
    """A file with no usable rows, shown with its issues while the current dataset stays loaded."""
    report = refused.report
    st.error(f"{escape_markdown(refused.source_name)} has no valid rows, so it was not loaded "
             f"({report.total_rows:,} of {report.total_rows:,} rows rejected). The current dataset is still loaded.")
    with panel("refused_file"):
        _render_issues(report)


def _remove_dataset() -> None:
    """Explicitly start over: back to the empty upload workspace."""
    st.session_state.pop(DATASET_KEY, None)
    st.session_state[SOURCE_MODE_KEY] = SOURCE_OPTIONS[0]


def _selected_source(samples: list[Path]):
    """The chosen file, read before drawing so the page can pick its layout first."""
    if st.session_state.get(SOURCE_MODE_KEY, SOURCE_OPTIONS[0]) == SOURCE_OPTIONS[0]:
        return st.session_state.get(SOURCE_UPLOAD_KEY)
    return st.session_state.get(SOURCE_SAMPLE_KEY, samples[0] if samples else None)


def _source_controls(samples: list[Path]) -> None:
    mode = st.radio("Source", SOURCE_OPTIONS, horizontal=True, key=SOURCE_MODE_KEY)
    if mode == SOURCE_OPTIONS[0]:
        st.file_uploader("CSV file", type=["csv"], key=SOURCE_UPLOAD_KEY)
    elif samples:
        st.selectbox("Sample file", samples, format_func=lambda p: p.name, key=SOURCE_SAMPLE_KEY)
    else:
        st.info("No sample datasets in data/sample yet.")


def _render_upload_workspace(samples: list[Path], load_error: str | None) -> None:
    """The page before a dataset is loaded: a large drop area beside the accepted format."""
    upload_column, format_column = st.columns((3, 2), gap="small")
    with upload_column, panel("data_source"):
        st.markdown("#### :material/upload_file: Load incident data")
        st.caption("Upload a CSV of point incidents, or start with the bundled sample dataset.")
        _source_controls(samples)
        if load_error is not None:
            st.error(f"This file cannot be used: {load_error}")
    with format_column, panel("data_format"):
        st.markdown("#### :material/table_view: Accepted CSV format")
        st.markdown(
            f"- **Required columns:** {', '.join(f'`{c}`' for c in REQUIRED_COLUMNS)}\n"
            f"- **Optional columns:** {', '.join(f'`{c}`' for c in OPTIONAL_COLUMNS)}\n"
            "- **Coordinates:** WGS84 decimal degrees\n"
            "- **Extra columns** are kept, and rows that fail validation are reported"
        )


def _render_dataset_bar(dataset: CleanDataset, status: str | None = None) -> None:
    """File name, counts and a badge: the validation status unless `status` is given."""
    report = dataset.report
    dataset_bar(escape_markdown(dataset.source_name),
                f"{report.total_rows:,} rows · {report.valid_rows:,} accepted · {report.rejected_rows:,} rejected",
                status or validation_status(report))


def validation_status(report) -> str:
    """Validation status KPI: Ready, Ready with rejections, or Unusable (from the existing report)."""
    if not report.is_usable:
        return "Unusable"
    return "Ready with rejections" if report.rejected_rows else "Ready"


def _render_validation(dataset: CleanDataset) -> None:
    report = dataset.report
    st.subheader("Validation summary")
    kpi_grid([
        ("Rows in file", f"{report.total_rows:,}"),
        ("Accepted", f"{report.valid_rows:,}"),
        ("Rejected", f"{report.rejected_rows:,}"),
        ("Validation status", validation_status(report)),
    ], DATA_KPI_KEY)

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

    with panel("data_workspace"):
        map_tab, issues_tab, preview_tab = st.tabs(
            ["Incident Map", f"Validation Issues ({len(report.issues):,})", "Data Preview"])
        with map_tab:
            _render_incident_map(dataset)
        with issues_tab:
            _render_issues(report)
        with preview_tab:
            if report.is_usable:
                st.caption(f"Accepted rows (first {min(PREVIEW_ROWS, report.valid_rows):,} of {report.valid_rows:,}).")
                preview = dataset.frame.head(PREVIEW_ROWS)
                st.dataframe(preview, width="stretch", column_config=_preview_column_config(preview))
                st.caption(TABLE_SCROLL_HINT)
            else:
                st.caption("No accepted rows to preview.")


def _render_issues(report) -> None:
    if report.issues:
        st.caption("Row numbers are 0-based data rows (row 0 = first line after the header).")
        issues = summarize_quality(report)
        st.dataframe(issues, hide_index=True, width="stretch",
                     column_config={column: column_label(column) for column in issues.columns})
    else:
        st.caption("No validation issues.")


def _preview_column_config(frame: pd.DataFrame) -> dict[str, Any]:
    """Readable headings; the index is the 0-based source row used by the validation messages."""
    config: dict[str, Any] = {"_index": st.column_config.NumberColumn(
        "Source Row", help="0-based data row in the file; matches the row numbers in Validation Issues", format="%d")}
    for column in frame.columns:
        config[column] = column_label(column)
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            dates = frame[column].dropna()
            date_only = bool((dates == dates.dt.normalize()).all())
            config[column] = st.column_config.DatetimeColumn(
                column_label(column), format="YYYY-MM-DD" if date_only else "YYYY-MM-DD HH:mm:ss")
    return config


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
    st_folium(build_incident_map(dataset), height=INCIDENT_MAP_HEIGHT_PX, use_container_width=True, returned_objects=[], key="incident_map")
