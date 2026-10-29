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


def render_page(name: str) -> None:
    """Render one page. History & Reports shows saved runs; reports arrive in Stage 9."""
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
    st.header(name)
    dataset = st.session_state.get("dataset")
    if dataset is None:
        st.info("No dataset loaded. Load and validate a CSV on the Data page first.")
        return
    if not dataset.report.is_usable:
        st.warning("The loaded dataset is unusable (no accepted incidents), so no analysis runs. Fix it on the Data page.")
        return
    if config is None:
        st.error("Analysis parameters are invalid; fix them in the sidebar. No analysis was run.")
        return
    results = _analysis_results(dataset, config)
    if name == "Clusters (DBSCAN)":
        _render_clusters_page(results)
    elif name == "Density (KDE)":
        _render_density_page(results)
    else:
        _render_summary_page(dataset, results)


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


# --- analysis lifecycle ----------------------------------------------------------------


def _sidebar_config() -> AnalysisConfig | None:
    """Analysis parameters from the sidebar; defaults from config; validated by the dataclasses."""
    d = DEFAULT_ANALYSIS_CONFIG
    sb = st.sidebar
    sb.subheader("Analysis parameters")
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
    try:
        entry["clusters"] = cluster_dataset(dataset, config)
    except AnalysisError as exc:
        entry["cluster_error"] = str(exc)
    try:
        entry["density"] = estimate_density(dataset, config)
    except AnalysisError as exc:
        entry["density_error"] = str(exc)
    try:
        entry["summary"] = summarize_results(dataset, entry["clusters"], entry["density"])
    except AnalysisError as exc:
        entry["summary_error"] = str(exc)
    st.session_state[CACHE_KEY] = entry
    return entry


# --- Clusters page ----------------------------------------------------------------------


def _render_clusters_page(results: dict[str, Any]) -> None:
    st.caption(
        "**Cluster map** — DBSCAN result on all accepted incidents. Coloured points = cluster members, "
        "small grey points = noise, circles = each cluster's centroid and radius_m. A thick black outline "
        "marks a candidate hotspot (size rule only, not statistical significance)."
    )
    if results["cluster_error"]:
        st.error(f"DBSCAN failed: {results['cluster_error']}")
        return
    clusters: ClusterResult = results["clusters"]
    frame = clusters.labeled_frame
    candidates = {c.cluster_label for c in clusters.clusters if c.is_candidate_hotspot}

    total, cands, noise = st.columns(3)
    total.metric("Clusters", len(clusters.clusters))
    cands.metric("Candidate hotspots", len(candidates))
    noise.metric("Noise incidents", f"{clusters.noise_count:,} of {len(frame):,}")

    st.sidebar.subheader("Display filters")
    st.sidebar.caption("Change only what the cluster map and the 'shown' bars display. "
                       "DBSCAN, KDE and the summary always use all accepted incidents.")
    severities = _category_filter(frame, "severity", "Severity (display only)")
    types = _category_filter(frame, "incident_type", "Incident type (display only)")
    show_noise = st.sidebar.checkbox("Show noise points", value=True, key="f_show_noise")
    candidates_only = st.sidebar.checkbox("Candidate hotspots only", value=False, key="f_candidates_only")

    mask = display_mask(frame, severities, types, show_noise, candidates if candidates_only else None)
    shown = int(mask.sum())
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
    st.dataframe(table, hide_index=True, width="stretch")
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
    fig.update_layout(barmode="group", title="Cluster sizes (black outline = candidate hotspot, size rule only)",
                      xaxis_title="Cluster label (an identifier, not a rank)", yaxis_title="Incidents",
                      legend_orientation="h")
    st.plotly_chart(fig, width="stretch", key="chart_cluster_sizes")


def _category_filter(frame: pd.DataFrame, column: str, label: str) -> set[str] | None:
    if column not in frame.columns:
        return None
    options = sorted(category_values(frame[column]).unique(), key=lambda v: (v == MISSING_LABEL, v))
    chosen = st.sidebar.multiselect(label, options, default=options, key=f"f_{column}")
    return set(chosen)


# --- Density page -----------------------------------------------------------------------


def _render_density_page(results: dict[str, Any]) -> None:
    st.caption(
        "**Density map** — the KDE surface computed from all accepted incidents, drawn grid cell by grid cell. "
        "Display filters do not apply here."
    )
    if results["density_error"]:
        st.error(f"KDE did not run: {results['density_error']}")
        return
    density = results["density"]
    p = density.params
    st_folium(build_density_map(density), height=520, use_container_width=True, returned_objects=[], key="density_map")
    st.markdown(
        f"- **Colour scale:** {DENSITY_LEGEND} {DENSITY_SCALE_NOTE} Cells below {DENSITY_TRANSPARENT_BELOW:.0%} "
        "of the grid maximum are drawn transparent so the basemap stays visible; the values themselves are unchanged.\n"
        f"- **High-density layer** (switch on in the map's layer control): cells with density ≥ the "
        f"{p['high_density_quantile']:.0%} quantile of this grid. This is relative to this analysis and grid "
        "extent only; it is not statistically significant risk.\n"
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
    st.dataframe(params_table, hide_index=True, width="stretch")


# --- Summary page -----------------------------------------------------------------------


def _render_summary_page(dataset: CleanDataset, results: dict[str, Any]) -> None:
    st.caption("Descriptive summary of all accepted incidents. Display filters on the Clusters page do not apply here.")
    for key, name in (("cluster_error", "DBSCAN"), ("density_error", "KDE")):
        if results[key]:
            st.warning(f"{name} did not run: {results[key]}")
    if results["summary_error"]:
        st.error(f"Summary failed: {results['summary_error']}")
        return
    s = results["summary"]
    a, b, c, d = st.columns(4)
    a.metric("Accepted incidents", f"{s.incident_count:,}")
    b.metric("Clusters", NOT_RUN if s.cluster_count is None else s.cluster_count)
    c.metric("Candidate hotspots", NOT_RUN if s.candidate_hotspot_count is None else s.candidate_hotspot_count)
    d.metric("Noise share", NOT_RUN if s.noise_share is None else f"{s.noise_share:.1%}")
    st.caption(
        f"Bounding box (min lat, min lon, max lat, max lon): {', '.join(f'{v:.5f}' for v in s.bounding_box)} · "
        f"Mean centre (lat, lon): {s.mean_center[0]:.5f}, {s.mean_center[1]:.5f}"
    )

    st.subheader("DBSCAN vs KDE (descriptive comparison)")
    mc = s.method_comparison
    if mc is None:
        st.info("Not available: the comparison needs both DBSCAN and KDE results.")
    else:
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
            )

    st.subheader("Incidents by category and date")
    for column, title in (("severity", "Severity"), ("incident_type", "Incident type")):
        counts = s.by_category.get(column)
        if counts:
            fig = go.Figure(go.Bar(x=list(counts), y=list(counts.values()), marker_color="#2e86c1"))
            fig.update_layout(title=f"Incidents by {title.lower()} (all accepted incidents)",
                              xaxis_title=title, yaxis_title="Incidents")
            st.plotly_chart(fig, width="stretch", key=f"chart_{column}")
    if not s.by_category:
        st.caption("No severity or incident_type column in this dataset.")
    timeline = incidents_by_period(dataset)
    if timeline["column_present"] and not timeline["counts"].empty:
        counts = timeline["counts"]
        fig = go.Figure(go.Bar(x=counts["period_start"], y=counts["incident_count"], marker_color="#2e86c1"))
        fig.update_layout(title=f"Incidents per {timeline['period']} (all accepted incidents with a valid date)",
                          xaxis_title=timeline["period"].capitalize(), yaxis_title="Incidents")
        st.plotly_chart(fig, width="stretch", key="chart_dates")
        if timeline["missing_dates"]:
            st.caption(f"{timeline['missing_dates']:,} incident(s) have no valid date and are not in this chart.")
    elif timeline["column_present"]:
        st.caption("incident_date is present but no incident has a valid ISO 8601 date, so no date chart is shown.")
    else:
        st.caption("No incident_date column in this dataset.")

    st.subheader("Notes and caveats")
    st.markdown("\n".join(f"- {n}" for n in s.notes + (mc.notes if mc else [])))

    _render_save_section(dataset, results)


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
        if not st.button("Save this run to history", key="save_run"):
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
        if not st.button("Generate reports", key="generate_reports"):
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
    st.header("History & Reports")
    st.subheader("Saved runs")
    try:
        runs = list_runs(HISTORY_LIMIT, db_path=HISTORY_DB_PATH)
    except (sqlite3.Error, OSError, ValueError) as exc:
        st.error(f"Could not read the run history: {exc}")
        runs = None
    if runs == []:
        st.info("No runs saved yet. Run an analysis and use 'Save this run to history' on the Summary page.")
    elif runs:
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
    st.header("Data")
    samples = list_sample_datasets()
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


def _render_validation(dataset: CleanDataset) -> None:
    report = dataset.report
    total, accepted, rejected = st.columns(3)
    total.metric("Rows in file", f"{report.total_rows:,}")
    accepted.metric("Accepted", f"{report.valid_rows:,}")
    rejected.metric("Rejected", f"{report.rejected_rows:,}")

    if not report.is_usable:
        st.error(
            "No valid rows remain, so this dataset is unusable. "
            "Spatial analysis will not run. Fix the issues below and upload again."
        )
    elif report.rejected_rows:
        st.warning(f"{report.rejected_rows:,} row(s) were rejected and excluded from analysis.")
    else:
        st.success("All rows passed validation.")

    if report.issues:
        st.subheader("Validation issues")
        st.caption("Row numbers are 0-based data rows (row 0 = first line after the header).")
        st.dataframe(summarize_quality(report), hide_index=True, width="stretch")

    present = ", ".join(report.optional_columns_present) or "none"
    extra = ", ".join(report.extra_columns_preserved) or "none"
    st.caption(f"Optional columns present: {present}. Extra columns preserved: {extra}.")

    _render_incident_map(dataset)

    if report.is_usable:
        st.subheader(f"Accepted rows (first {min(PREVIEW_ROWS, report.valid_rows):,})")
        st.dataframe(dataset.frame.head(PREVIEW_ROWS), width="stretch")


def _render_incident_map(dataset: CleanDataset) -> None:
    """Base point map of accepted incidents. No clustering or density layers."""
    st.subheader("Incident map")
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
