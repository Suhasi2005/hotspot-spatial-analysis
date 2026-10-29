"""CSV and PDF exports. Owner: Member 5 (Reporting).

Reports must state the method limitations: clusters and density surfaces are
descriptive; candidate hotspots are not statistically significant hotspots.
"""

from __future__ import annotations

from pathlib import Path

from config.settings import REPORTS_DIR
from modules.contracts import AnalysisRun


def export_csv(run: AnalysisRun, out_dir: Path = REPORTS_DIR) -> list[Path]:
    """Write labelled incidents and cluster summaries as CSV. Stage 9."""
    raise NotImplementedError("Stage 9: report_generator.export_csv")


def export_pdf(run: AnalysisRun, out_dir: Path = REPORTS_DIR) -> Path:
    """Write a ReportLab PDF summary with parameters and limitations. Stage 9."""
    raise NotImplementedError("Stage 9: report_generator.export_pdf")
