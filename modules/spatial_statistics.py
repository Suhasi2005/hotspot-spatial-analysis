"""Descriptive spatial statistics and method comparison. Owners: Members 3 and 5."""

from __future__ import annotations

from modules.contracts import CleanDataset, ClusterResult, DensityResult, SpatialSummary


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS 84 points. Stage 4."""
    raise NotImplementedError("Stage 4: spatial_statistics.haversine_m")


def summarize(
    dataset: CleanDataset,
    clusters: ClusterResult | None,
    density: DensityResult | None,
) -> SpatialSummary:
    """Build descriptive statistics; tolerates either analysis being absent. Stage 6."""
    raise NotImplementedError("Stage 6: spatial_statistics.summarize")
