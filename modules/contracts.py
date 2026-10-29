"""Shared data contracts passed between modules.

These types are the integration boundary for the five module owners. Change
them only by team agreement and update docs/module_interfaces.md in the same
commit. Nothing here imports Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from config.settings import AnalysisConfig

# Column added by DBSCAN to the incident frame. -1 = noise (sklearn convention).
CLUSTER_LABEL_COLUMN = "cluster_label"
NOISE_LABEL = -1


class DataValidationError(ValueError):
    """Raised when a dataset cannot be used at all (e.g. a required column is missing)."""


class AnalysisError(RuntimeError):
    """Raised when an analytical step fails for a reason the user must see."""


@dataclass
class ValidationIssue:
    """One data-quality problem, tied to source rows where possible."""

    code: str                 # e.g. "LAT_OUT_OF_RANGE", "MISSING_COORDINATE"
    message: str
    row_indices: list[int] = field(default_factory=list)
    severity: str = "error"   # "error" = row excluded, "warning" = row kept


@dataclass
class ValidationReport:
    """Outcome of validating one raw dataset."""

    total_rows: int
    valid_rows: int
    rejected_rows: int
    issues: list[ValidationIssue] = field(default_factory=list)
    optional_columns_present: list[str] = field(default_factory=list)
    extra_columns_preserved: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """False when no row survived validation; analysis must not run then."""
        return self.valid_rows > 0


@dataclass
class CleanDataset:
    """Validated incidents ready for spatial analysis.

    frame: pandas DataFrame with at least incident_id (str), latitude (float64),
    longitude (float64), all within legal ranges and non-null. Optional columns,
    when present, are coerced per docs/dataset_specification.md.
    """

    frame: pd.DataFrame
    source_name: str
    report: ValidationReport


@dataclass
class ClusterSummary:
    """Per-cluster statistics. A summary row for noise is never produced.

    centroid_lat / centroid_lon: arithmetic means of the members' latitudes and
    longitudes in degrees. radius_m: maximum haversine distance (metres) from
    that centroid to any member. This approximation suits a compact, city-scale
    study area away from the poles and the antimeridian. Elongated or curved
    clusters (e.g. along a highway) are poorly described by centroid + radius
    and may need a hull or another shape measure later.
    """

    cluster_label: int
    incident_count: int
    centroid_lat: float
    centroid_lon: float
    radius_m: float               # max haversine distance from centroid to a member
    is_candidate_hotspot: bool    # per CandidateHotspotCriteria; NOT significance


@dataclass
class ClusterResult:
    """DBSCAN output."""

    labeled_frame: pd.DataFrame   # CleanDataset.frame + CLUSTER_LABEL_COLUMN
    clusters: list[ClusterSummary]
    noise_count: int
    params: dict[str, Any]        # eps_m, eps_rad, min_samples, metric


@dataclass
class DensityResult:
    """KDE output evaluated on a regular lat/lon grid.

    grid_lat, grid_lon: 1-D float64 axes in degrees, ascending.
    density: 2-D float64 array, shape (len(grid_lat), len(grid_lon)), so
    density[i, j] is the estimate at (grid_lat[i], grid_lon[j]) — rows follow
    latitude, columns follow longitude.

    The nominal cell size (KDEParams.grid_cell_m) is converted to degree steps
    with a local approximation at the grid's mean latitude phi:
        lat_step_deg ~= cell_m / 110540
        lon_step_deg ~= cell_m / (111320 * cos(phi))
    Cells are therefore only approximately square and equal-area; the error
    grows with the north-south extent of the study area. These are not exact
    conversions.

    Values are relative density (sklearn normalises in flat space) and are
    meaningful for ranking/comparison, not as incident counts or per-km2 rates.
    """

    grid_lat: npt.NDArray[np.float64]
    grid_lon: npt.NDArray[np.float64]
    density: npt.NDArray[np.float64]
    high_density_threshold: float
    params: dict[str, Any]        # bandwidth_m, bandwidth_rad, kernel, grid_cell_m


@dataclass
class ClusterOverlap:
    """One DBSCAN cluster's members compared with KDE high-density grid nodes.

    incident_count = eligible_members + outside_grid_members.
    high_density_share = members_at_high_density / eligible_members, or None
    when eligible_members == 0.
    """

    cluster_label: int
    incident_count: int
    eligible_members: int         # members inside the KDE grid extent
    outside_grid_members: int
    members_at_high_density: int
    high_density_share: float | None
    is_candidate_hotspot: bool    # copied from the ClusterSummary; NOT significance


@dataclass
class MethodComparison:
    """Descriptive, point-based comparison of DBSCAN labels with KDE high density.

    Each incident inside the KDE grid extent ("eligible") is read at its
    nearest grid node and classed high-density if density >= threshold.
    Incidents outside the extent are counted in outside_grid_count only.

    2x2 table over eligible incidents (rows: DBSCAN, columns: KDE):
        clustered_high | clustered_not_high | = clustered_eligible
        noise_high     | noise_not_high     | = noise_eligible
        = high_density_eligible | = not_high_density_eligible | = eligible_count
    total_incidents = eligible_count + outside_grid_count.
    Shares are None when their denominator is 0. Descriptive only: no
    statistical association or significance is implied.
    """

    clustered_high: int
    clustered_not_high: int
    noise_high: int
    noise_not_high: int
    clustered_eligible: int
    noise_eligible: int
    high_density_eligible: int
    not_high_density_eligible: int
    eligible_count: int
    outside_grid_count: int
    total_incidents: int
    clustered_high_share: float | None   # clustered_high / clustered_eligible
    noise_high_share: float | None       # noise_high / noise_eligible
    per_cluster: list[ClusterOverlap] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class SpatialSummary:
    """Descriptive statistics over the dataset and the analytical results.

    cluster_count, candidate_hotspot_count and noise_share are None when DBSCAN
    was not run (0 / 0.0 mean it ran and the value is zero). noise_share =
    noise incidents / accepted incidents. method_comparison is set only when
    both DBSCAN and KDE results were supplied.
    """

    incident_count: int
    bounding_box: tuple[float, float, float, float]  # min_lat, min_lon, max_lat, max_lon
    mean_center: tuple[float, float]                 # (mean lat, mean lon) in degrees
    cluster_count: int | None
    candidate_hotspot_count: int | None
    noise_share: float | None
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)  # e.g. {"severity": {...}}
    notes: list[str] = field(default_factory=list)
    method_comparison: MethodComparison | None = None


@dataclass
class AnalysisRun:
    """Everything one analysis produced; the input to dashboard, history and reports."""

    run_id: str
    created_at: datetime
    config: AnalysisConfig
    dataset: CleanDataset
    clusters: ClusterResult | None
    density: DensityResult | None
    summary: SpatialSummary | None
