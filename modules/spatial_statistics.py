"""Descriptive spatial statistics and method comparison. Owners: Members 3 and 5."""

from __future__ import annotations

import math

from config.settings import EARTH_RADIUS_M
from modules.contracts import CleanDataset, ClusterResult, DensityResult, SpatialSummary


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two points given in degrees.

    Uses the haversine formula on a sphere of radius EARTH_RADIUS_M — the same
    sphere and radius DBSCAN uses for eps, so radius_m and eps are comparable.
    Scalar inputs only (contract); implemented by Member 2 in Stage 4.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def summarize(
    dataset: CleanDataset,
    clusters: ClusterResult | None,
    density: DensityResult | None,
) -> SpatialSummary:
    """Build descriptive statistics; tolerates either analysis being absent. Stage 6."""
    raise NotImplementedError("Stage 6: spatial_statistics.summarize")
