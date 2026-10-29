"""Analysis workflow orchestration. Owner: Member 5 (Integration).

Single entry point the UI calls: load -> validate -> DBSCAN -> KDE -> summary
-> persist. Streamlit-free so the whole pipeline is testable headless.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from config.settings import DB_PATH, AnalysisConfig, StudyArea
from modules.contracts import (
    AnalysisError,
    AnalysisRun,
    CleanDataset,
    ClusterResult,
    DensityResult,
    SpatialSummary,
)
from modules.data_manager import load_raw_dataset
from modules.database import save_run
from modules.data_validator import validate_and_clean
from modules.dbscan_analysis import run_dbscan
from modules.density_analysis import run_kde
from modules.spatial_statistics import summarize


def load_and_validate(
    source: Path | BinaryIO,
    source_name: str | None = None,
    study_area: StudyArea | None = None,
) -> CleanDataset:
    """Load a CSV and validate it (the Stage 2 slice of the workflow).

    Raises DataValidationError when the file cannot be used at all. Otherwise
    returns a CleanDataset; callers must check dataset.report.is_usable before
    running any spatial analysis.
    """
    raw, name = load_raw_dataset(source, source_name)
    return validate_and_clean(raw, name, study_area)


def cluster_dataset(dataset: CleanDataset, config: AnalysisConfig) -> ClusterResult:
    """Run DBSCAN on a validated dataset (the Stage 4 slice of the workflow).

    Refuses an unusable dataset before DBSCAN is reached. Raises AnalysisError.
    """
    if not dataset.report.is_usable:
        raise AnalysisError("Clustering skipped: the dataset is unusable (no accepted incidents).")
    return run_dbscan(dataset, config.dbscan, config.hotspot)


def estimate_density(dataset: CleanDataset, config: AnalysisConfig) -> DensityResult:
    """Run KDE on a validated dataset (the Stage 5 slice of the workflow).

    Refuses an unusable dataset before KDE is reached. Uses config.kde and
    config.study_area. Raises AnalysisError.
    """
    if not dataset.report.is_usable:
        raise AnalysisError("Density estimation skipped: the dataset is unusable (no accepted incidents).")
    return run_kde(dataset, config.kde, config.study_area)


def summarize_results(
    dataset: CleanDataset,
    clusters: ClusterResult | None,
    density: DensityResult | None,
) -> SpatialSummary:
    """Thin wrapper over spatial_statistics.summarize (Stage 6 behaviour unchanged)."""
    return summarize(dataset, clusters, density)


def run_analysis(
    source: Path | BinaryIO,
    config: AnalysisConfig,
    source_name: str | None = None,
    persist: bool = True,
    *,
    db_path: Path = DB_PATH,
) -> AnalysisRun:
    """Load -> validate -> (DBSCAN, KDE, summary) -> AnalysisRun -> optional history row.

    - An unusable dataset stops before DBSCAN/KDE: the run has clusters,
      density and summary None, and is still saved when persist=True.
    - Errors propagate (DataValidationError, AnalysisError, sqlite3.Error,
      OSError). A failed load or analysis is never saved.
    - persist=False never opens or creates the database.
    """
    dataset = load_and_validate(source, source_name, config.study_area)
    clusters = density = summary = None
    if dataset.report.is_usable:
        clusters = cluster_dataset(dataset, config)
        density = estimate_density(dataset, config)
        summary = summarize_results(dataset, clusters, density)
    run = _build_run(dataset, config, clusters, density, summary)
    if persist:
        save_run(run, db_path)
    return run


def record_run(
    dataset: CleanDataset,
    config: AnalysisConfig,
    clusters: ClusterResult | None,
    density: DensityResult | None,
    summary: SpatialSummary | None,
    *,
    db_path: Path = DB_PATH,
) -> AnalysisRun:
    """Save results that were already computed (the dashboard's Save button).

    Accepts only a complete run: for a usable dataset, clusters, density and
    summary must all be present (a failed analysis is not persisted), the
    summary must equal summarize_results(dataset, clusters, density), which
    also proves the results belong to this dataset, and `config` must match
    the results (_check_config_matches_results). For an unusable dataset all
    three must be None; there are no results to check `config` against.
    Raises AnalysisError before anything is written; storage errors propagate.
    """
    results = (clusters, density, summary)
    if dataset.report.is_usable:
        if any(r is None for r in results):
            raise AnalysisError("Only complete runs are saved: DBSCAN, KDE and the summary must all have succeeded.")
        if summarize_results(dataset, clusters, density) != summary:
            raise AnalysisError("The summary does not match these DBSCAN/KDE results; the run was not saved.")
        _check_config_matches_results(dataset, config, clusters, density)
    elif any(r is not None for r in results):
        raise AnalysisError("An unusable dataset cannot carry analysis results.")
    run = _build_run(dataset, config, clusters, density, summary)
    save_run(run, db_path)
    return run


def _check_config_matches_results(
    dataset: CleanDataset, config: AnalysisConfig, clusters: ClusterResult, density: DensityResult
) -> None:
    """Raise AnalysisError unless `config` is consistent with how the results were produced.

    Checked against what the results record: DBSCAN eps_m/min_samples; KDE
    bandwidth_m/kernel/grid_cell_m/high_density_quantile; the study area (KDE
    grid source and extent, and no accepted incident outside the box); and
    min_incidents through its only effect, the candidate-hotspot flags.
    Not checkable from results: random_seed and min_density_per_km2 (neither
    affects any result), and min_incidents values that yield identical flags.
    """
    problems: list[str] = []
    cp, dp = clusters.params, density.params
    for name, recorded, configured in (
        ("dbscan.eps_m", cp.get("eps_m"), config.dbscan.eps_m),
        ("dbscan.min_samples", cp.get("min_samples"), config.dbscan.min_samples),
        ("kde.bandwidth_m", dp.get("bandwidth_m"), config.kde.bandwidth_m),
        ("kde.kernel", dp.get("kernel"), config.kde.kernel),
        ("kde.grid_cell_m", dp.get("grid_cell_m"), config.kde.grid_cell_m),
        ("kde.high_density_quantile", dp.get("high_density_quantile"), config.kde.high_density_quantile),
    ):
        if recorded != configured:
            problems.append(f"{name}: results used {recorded!r}, configuration says {configured!r}")

    area = config.study_area
    if area is None:
        if dp.get("grid_source") != "data_extent_padded":
            problems.append("study_area: configuration has none, but the KDE grid came from a study area")
    else:
        box = {"south": area.min_lat, "north": area.max_lat, "west": area.min_lon, "east": area.max_lon}
        if dp.get("grid_source") != "study_area" or dp.get("grid_extent") != box:
            problems.append(f"study_area: KDE grid {dp.get('grid_source')!r} {dp.get('grid_extent')!r} is not the box {box!r}")
        lat = dataset.frame["latitude"].to_numpy(dtype="float64")
        lon = dataset.frame["longitude"].to_numpy(dtype="float64")
        if not (((lat >= area.min_lat) & (lat <= area.max_lat) & (lon >= area.min_lon) & (lon <= area.max_lon)).all()):
            problems.append("study_area: the dataset has accepted incidents outside the configured box")

    min_incidents = config.hotspot.min_incidents
    wrong = [c.cluster_label for c in clusters.clusters if c.is_candidate_hotspot != (c.incident_count >= min_incidents)]
    if wrong:
        problems.append(f"hotspot.min_incidents={min_incidents!r} contradicts the candidate flags of clusters {wrong}")

    if problems:
        raise AnalysisError("Configuration does not match these results; the run was not saved. " + "; ".join(problems))


def _build_run(
    dataset: CleanDataset,
    config: AnalysisConfig,
    clusters: ClusterResult | None,
    density: DensityResult | None,
    summary: SpatialSummary | None,
) -> AnalysisRun:
    return AnalysisRun(
        run_id=uuid.uuid4().hex,
        created_at=datetime.now(timezone.utc),
        config=config,
        dataset=dataset,
        clusters=clusters,
        density=density,
        summary=summary,
    )
