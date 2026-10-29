"""Analysis workflow orchestration. Owner: Member 5 (Integration).

Single entry point the UI calls: load -> validate -> DBSCAN -> KDE -> summary
-> persist. Streamlit-free so the whole pipeline is testable headless.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from config.settings import AnalysisConfig
from modules.contracts import AnalysisRun


def run_analysis(
    source: Path | BinaryIO,
    config: AnalysisConfig,
    source_name: str | None = None,
    persist: bool = True,
) -> AnalysisRun:
    """Execute the full workflow and return its results. Implemented in Stage 8."""
    raise NotImplementedError("Stage 8: app_controller.run_analysis")
