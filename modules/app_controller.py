"""Analysis workflow orchestration. Owner: Member 5 (Integration).

Single entry point the UI calls: load -> validate -> DBSCAN -> KDE -> summary
-> persist. Streamlit-free so the whole pipeline is testable headless.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from config.settings import DB_PATH, REPORTS_DIR, AnalysisConfig, StudyArea
from modules.contracts import (
    AnalysisError,
    AnalysisRun,
    CleanDataset,
    ClusterResult,
    DensityResult,
    SpatialSummary,
)
from modules.data_manager import load_raw_dataset
from modules.database import get_run, save_run, set_report_paths
from modules.report_generator import export_csv, export_pdf
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


def generate_reports(
    run: AnalysisRun,
    out_dir: Path = REPORTS_DIR,
    *,
    db_path: Path = DB_PATH,
) -> list[Path]:
    """Write incidents.csv, clusters.csv and report.pdf for a saved run and register them.

    Steps: (1) check eligibility — a usable dataset with complete results, a
    history row for run.run_id whose config and row counts match the run, and
    no reports registered yet; (2) refuse if out_dir/<run_id> already exists
    (never overwrite; once per run); (3) write the files into a new temporary
    folder inside out_dir; (4) check them (non-empty CSVs with a UTF-8 BOM, a
    PDF with %PDF-/%%EOF); (5) rename the temporary folder to out_dir/<run_id>;
    (6) register the paths, relative to out_dir, with set_report_paths.

    Not a true transaction across disk and database: on any failure the
    folders created by this attempt (and out_dir itself if this attempt
    created it and it is empty) are removed, the database is left unchanged,
    and the error is raised. Nothing that existed before is deleted. The run
    is not mutated. Returns the final absolute paths.
    """
    _check_report_eligibility(run, db_path)
    out_dir = Path(out_dir)
    final_dir = out_dir / run.run_id
    if final_dir.exists():
        raise FileExistsError(f"Reports folder {final_dir.name!r} already exists; reports are generated once per run.")

    created_root = not out_dir.exists()
    out_dir.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    moved = False
    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{run.run_id}.", dir=out_dir))
        files = export_csv(run, staging) + [export_pdf(run, staging)]
        _check_report_files(files)
        os.rename(staging, final_dir)                       # fails if final_dir appeared meanwhile (Windows)
        moved = True
        final_paths = [final_dir / f.name for f in files]
        set_report_paths(run.run_id, final_paths, db_path, reports_dir=out_dir)
        return final_paths
    except BaseException:
        if moved:
            shutil.rmtree(final_dir, ignore_errors=True)    # created by this attempt's rename
        elif staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        if created_root:
            try:
                out_dir.rmdir()                              # only if empty
            except OSError:
                pass
        raise


def _check_report_eligibility(run: AnalysisRun, db_path: Path) -> None:
    if not run.dataset.report.is_usable:
        raise AnalysisError("Reports are only generated for usable datasets.")
    if run.clusters is None or run.density is None or run.summary is None:
        raise AnalysisError("Reports are only generated for complete runs (DBSCAN, KDE and summary).")
    row = get_run(run.run_id, db_path)
    if row is None:
        raise AnalysisError("Reports are only generated for runs saved to the history; save this run first.")
    if (row["config"], row["source_name"], row["total_rows"], row["valid_rows"]) != (
        run.config, run.dataset.source_name, run.dataset.report.total_rows, run.dataset.report.valid_rows
    ):
        raise AnalysisError("The saved history row does not match this run; reports were not generated.")
    if row["report_paths"] is not None:
        raise AnalysisError("Reports are already registered for this run; they are generated once per run.")


def _check_report_files(files: list[Path]) -> None:
    for path in files:
        data = path.read_bytes()
        if path.suffix == ".csv":
            if not data.startswith(b"\xef\xbb\xbf") or len(data) <= 3:
                raise OSError(f"Generated {path.name} is empty or not UTF-8 with BOM.")
        elif not (data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")):
            raise OSError(f"Generated {path.name} is not a complete PDF.")


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
