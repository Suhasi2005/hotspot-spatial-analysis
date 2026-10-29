"""Schema validation and cleaning. Owner: Member 1 (Data Management)."""

from __future__ import annotations

import pandas as pd

from config.settings import StudyArea
from modules.contracts import CleanDataset, ValidationReport


def validate_and_clean(
    raw: pd.DataFrame,
    source_name: str,
    study_area: StudyArea | None = None,
) -> CleanDataset:
    """Validate a raw frame against the shared schema and return clean rows.

    Rules (docs/dataset_specification.md):
    - A missing required column raises DataValidationError.
    - Null/blank incident_id -> row rejected (MISSING_ID).
    - Repeated incident_id -> first occurrence kept, later ones rejected
      (DUPLICATE_ID, with their row indices). This is the project's only
      duplicate rule.
    - Coordinates must be numeric, non-null and in legal range, else the row
      is rejected and recorded in the report.
    - Optional columns are coerced; extra columns are preserved; no value is
      imputed.
    - Zero surviving rows does NOT raise: an empty CleanDataset is returned
      with report.is_usable == False.

    Implemented in Stage 2.
    """
    raise NotImplementedError("Stage 2: data_validator.validate_and_clean")


def summarize_quality(report: ValidationReport) -> pd.DataFrame:
    """Flatten a ValidationReport into a table for display/export. Stage 2."""
    raise NotImplementedError("Stage 2: data_validator.summarize_quality")
