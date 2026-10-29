"""Geodesic DBSCAN clustering. Owner: Member 2 (DBSCAN Analysis).

Clustering runs with metric="haversine" on [latitude, longitude] in RADIANS.
eps is converted from metres with metres_to_radians(). Clusters are density-
connected groups of points; they are not statistically significant hotspots.
"""

from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np
from sklearn.cluster import DBSCAN

from config.settings import EARTH_RADIUS_M, CandidateHotspotCriteria, DBSCANParams
from modules.contracts import (
    CLUSTER_LABEL_COLUMN,
    NOISE_LABEL,
    AnalysisError,
    CleanDataset,
    ClusterResult,
    ClusterSummary,
)
from modules.spatial_statistics import haversine_m

METRIC = "haversine"
ALGORITHM = "ball_tree"
# Largest meaningful eps: half the circumference of the mean-radius sphere (the
# antipodal distance). Compared in metres, so no radians rounding is involved.
MAX_EPS_M = math.pi * EARTH_RADIUS_M


def metres_to_radians(distance_m: float) -> float:
    """Convert a ground distance to an angular distance on the mean-radius sphere."""
    return distance_m / EARTH_RADIUS_M


def run_dbscan(
    dataset: CleanDataset,
    params: DBSCANParams,
    criteria: CandidateHotspotCriteria,
) -> ClusterResult:
    """Cluster incidents with haversine DBSCAN and summarise each cluster.

    - Input: a usable CleanDataset (degrees). Raises AnalysisError if the
      dataset is unusable/empty, a parameter is invalid, or the frame already
      has a CLUSTER_LABEL_COLUMN.
    - Coordinates are taken by row POSITION as [lat, lon], converted to
      radians; eps_rad = eps_m / EARTH_RADIUS_M. min_samples counts the point
      itself (scikit-learn semantics).
    - labeled_frame is a copy of dataset.frame — same rows, order and source
      index — plus CLUSTER_LABEL_COLUMN attached by position. Noise is -1.
    - clusters: one ClusterSummary per real cluster, ascending label; none for
      noise. Labels are arbitrary identifiers, not rankings.
    - Fewer points than min_samples is not an error: every point is noise.
    - is_candidate_hotspot = incident_count >= criteria.min_incidents. This is a
      size rule only; it implies no statistical significance.
      min_density_per_km2 is not used (no agreed area calculation yet).

    Deterministic for a fixed input order. The input dataset is not mutated.
    """
    _validate(dataset, params, criteria)
    frame = dataset.frame
    lat = frame["latitude"].to_numpy(dtype="float64")
    lon = frame["longitude"].to_numpy(dtype="float64")
    eps_rad = metres_to_radians(float(params.eps_m))
    min_samples = int(params.min_samples)

    model = DBSCAN(eps=eps_rad, min_samples=min_samples, metric=METRIC, algorithm=ALGORITHM)
    labels = model.fit_predict(np.radians(np.column_stack([lat, lon])))

    labeled = frame.copy()
    labeled[CLUSTER_LABEL_COLUMN] = labels  # positional: same order as the rows fed to sklearn

    clusters = [
        _summarize_cluster(int(label), lat[labels == label], lon[labels == label], criteria)
        for label in sorted(set(labels.tolist()) - {NOISE_LABEL})
    ]
    return ClusterResult(
        labeled_frame=labeled,
        clusters=clusters,
        noise_count=int(np.count_nonzero(labels == NOISE_LABEL)),
        params={
            "eps_m": float(params.eps_m),
            "eps_rad": eps_rad,
            "min_samples": min_samples,
            "metric": METRIC,
            "algorithm": ALGORITHM,
        },
    )


def _summarize_cluster(
    label: int, lats: np.ndarray, lons: np.ndarray, criteria: CandidateHotspotCriteria
) -> ClusterSummary:
    """Arithmetic-mean centroid (degrees) and max haversine distance to a member (metres)."""
    centroid_lat = float(lats.mean())
    centroid_lon = float(lons.mean())
    radius_m = max(haversine_m(centroid_lat, centroid_lon, float(a), float(b)) for a, b in zip(lats, lons))
    count = int(lats.size)
    return ClusterSummary(
        cluster_label=label,
        incident_count=count,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        radius_m=radius_m,
        is_candidate_hotspot=count >= criteria.min_incidents,
    )


def _validate(dataset: CleanDataset, params: DBSCANParams, criteria: CandidateHotspotCriteria) -> None:
    if not dataset.report.is_usable or dataset.frame.empty:
        raise AnalysisError("DBSCAN cannot run: the dataset is unusable or has no accepted incidents.")
    if CLUSTER_LABEL_COLUMN in dataset.frame.columns:
        raise AnalysisError(
            f"The dataset already has a column named {CLUSTER_LABEL_COLUMN!r}; rename it before clustering."
        )
    eps = params.eps_m
    if isinstance(eps, bool) or not isinstance(eps, Real) or not math.isfinite(eps) or eps <= 0:
        raise AnalysisError(f"eps_m must be a finite number of metres > 0 (got {eps!r}).")
    if eps > MAX_EPS_M:
        raise AnalysisError(
            f"eps_m must not exceed half the Earth's circumference, {MAX_EPS_M!r} m "
            f"(pi x {EARTH_RADIUS_M} m); got {eps!r}."
        )
    if not _is_positive_int(params.min_samples):
        raise AnalysisError(f"min_samples must be an integer >= 1 (got {params.min_samples!r}).")
    if not _is_positive_int(criteria.min_incidents):
        raise AnalysisError(f"min_incidents must be an integer >= 1 (got {criteria.min_incidents!r}).")
    lat = dataset.frame["latitude"].to_numpy(dtype="float64")
    lon = dataset.frame["longitude"].to_numpy(dtype="float64")
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()):
        raise AnalysisError("DBSCAN cannot run: the dataset contains missing or non-finite coordinates.")
    if (np.abs(lat) > 90).any() or (np.abs(lon) > 180).any():
        raise AnalysisError("DBSCAN cannot run: the dataset contains out-of-range coordinates.")


def _is_positive_int(value: object) -> bool:
    return isinstance(value, Integral) and not isinstance(value, bool) and value >= 1
