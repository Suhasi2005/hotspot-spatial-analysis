"""Analysis workflow orchestration. Owner: Member 5 (Integration).

Single entry point the UI calls: load -> validate -> DBSCAN -> KDE -> summary
-> persist. Streamlit-free so the whole pipeline is testable headless.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from config.settings import AnalysisConfig, StudyArea
from modules.contracts import (
    AnalysisError,
    AnalysisRun,
    CleanDataset,
    ClusterResult,
    DensityResult,
    SpatialSummary,
)
from modules.data_manager import load_raw_dataset
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
) -> AnalysisRun:
    """Execute the full workflow and return its results. Implemented in Stage 8."""
    raise NotImplementedError("Stage 8: app_controller.run_analysis")
