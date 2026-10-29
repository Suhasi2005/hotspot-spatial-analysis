"""Geodesic DBSCAN clustering. Owner: Member 2 (DBSCAN Analysis).

Clustering runs with metric="haversine" on [latitude, longitude] in RADIANS.
eps is converted from metres with metres_to_radians(). Clusters are density-
connected groups of points; they are not statistically significant hotspots.
"""

from __future__ import annotations

from config.settings import EARTH_RADIUS_M, CandidateHotspotCriteria, DBSCANParams
from modules.contracts import CleanDataset, ClusterResult


def metres_to_radians(distance_m: float) -> float:
    """Convert a ground distance to an angular distance on the mean-radius sphere."""
    return distance_m / EARTH_RADIUS_M


def run_dbscan(
    dataset: CleanDataset,
    params: DBSCANParams,
    criteria: CandidateHotspotCriteria,
) -> ClusterResult:
    """Cluster incidents and summarise each cluster. Implemented in Stage 4."""
    raise NotImplementedError("Stage 4: dbscan_analysis.run_dbscan")
