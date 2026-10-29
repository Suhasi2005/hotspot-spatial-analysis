"""Analysis workflow orchestration. Owner: Member 5 (Integration).

Single entry point the UI calls: load -> validate -> DBSCAN -> KDE -> summary
-> persist. Streamlit-free so the whole pipeline is testable headless.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from config.settings import AnalysisConfig, StudyArea
from modules.contracts import AnalysisRun, CleanDataset
from modules.data_manager import load_raw_dataset
from modules.data_validator import validate_and_clean


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


def run_analysis(
    source: Path | BinaryIO,
    config: AnalysisConfig,
    source_name: str | None = None,
    persist: bool = True,
) -> AnalysisRun:
    """Execute the full workflow and return its results. Implemented in Stage 8."""
    raise NotImplementedError("Stage 8: app_controller.run_analysis")
