"""Dataset loading and listing. Owner: Member 1 (Data Management)."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import pandas as pd

from config.settings import SAMPLE_DATA_DIR, SUPPORTED_UPLOAD_EXTENSIONS
from modules.contracts import DataValidationError  # noqa: F401  raised by load_raw_dataset (Stage 2)


def list_sample_datasets(directory: Path = SAMPLE_DATA_DIR) -> list[Path]:
    """Return the sample/demo CSV files available under data/sample."""
    return sorted(p for p in directory.glob("*") if p.suffix.lower() in SUPPORTED_UPLOAD_EXTENSIONS)


def load_raw_dataset(source: Path | BinaryIO, source_name: str | None = None) -> tuple[pd.DataFrame, str]:
    """Read a CSV from disk or an uploaded file object without altering values.

    Returns (raw_frame, source_name). Raises DataValidationError for unreadable
    or unsupported files. Implemented in Stage 2.
    """
    raise NotImplementedError("Stage 2: data_manager.load_raw_dataset")
