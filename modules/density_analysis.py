"""Kernel density estimation. Owner: Member 3 (KDE and Spatial Density).

KernelDensity runs with metric="haversine" on radians; bandwidth is supplied in
metres and converted. The surface shows estimated relative density only — high
density is not proof of statistical significance.
"""

from __future__ import annotations

from config.settings import KDEParams, StudyArea
from modules.contracts import CleanDataset, DensityResult


def run_kde(
    dataset: CleanDataset,
    params: KDEParams,
    study_area: StudyArea | None = None,
) -> DensityResult:
    """Fit KDE and evaluate it on a grid over the study area (or data extent). Stage 5."""
    raise NotImplementedError("Stage 5: density_analysis.run_kde")
