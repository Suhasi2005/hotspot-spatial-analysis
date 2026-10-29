"""Descriptive spatial statistics and method comparison. Owners: Members 3 and 5."""

from __future__ import annotations

import math
from numbers import Integral
from typing import Any

import numpy as np
import pandas as pd

from config.settings import EARTH_RADIUS_M
from modules.contracts import (
    CLUSTER_LABEL_COLUMN,
    NOISE_LABEL,
    AnalysisError,
    CleanDataset,
    ClusterOverlap,
    ClusterResult,
    DensityResult,
    MethodComparison,
    SpatialSummary,
)

CATEGORY_COLUMNS: tuple[str, ...] = ("severity", "incident_type")
MISSING_CATEGORY = "(missing)"

STANDARD_NOTES: tuple[str, ...] = (
    "DBSCAN clusters are descriptive density-connected groupings of incidents.",
    "KDE high-density locations are descriptive density estimates; KDE values are relative "
    "density scores, not incident counts or incidents per km2.",
    "Candidate hotspots follow the configured DBSCAN size criterion (min_incidents) only.",
    "None of these results establishes statistical significance; no significance test was run.",
    "mean_center is the arithmetic mean of latitudes and longitudes in degrees: suitable for "
    "city-scale data, not for data spanning the 180-degree meridian.",
)
COMPARISON_NOTES: tuple[str, ...] = (
    "The DBSCAN/KDE comparison is descriptive; it does not establish statistical association, "
    "significance, or independent validation of either method.",
    "Each incident is matched to its nearest KDE grid node (an approximation of up to half a "
    "grid cell per axis); ties between two nodes go to the southern/western node.",
    "High density means density >= the run's high_density_threshold, a quantile of this grid: "
    "specific to this analysis and grid extent, not an absolute standard.",
    "Incidents outside the KDE grid extent are excluded from the comparison denominators and "
    "counted in outside_grid_count.",
)


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
    """Descriptive statistics for a usable dataset and whichever analyses were run.

    - incident_count, bounding_box (min_lat, min_lon, max_lat, max_lon) and
      mean_center (mean lat, mean lon) come from dataset.frame by position.
    - cluster_count, candidate_hotspot_count, noise_share come from `clusters`,
      or are None when it is None. noise_share = noise incidents / accepted
      incidents.
    - by_category counts severity / incident_type when present, missing values
      under "(missing)".
    - method_comparison = compare_methods(...) only when both results exist.

    Raises AnalysisError for an unusable/empty dataset or results that do not
    match it. Inputs are not mutated.
    """
    frame = dataset.frame
    if not dataset.report.is_usable or frame.empty:
        raise AnalysisError("Summary cannot run: the dataset is unusable or has no accepted incidents.")
    lat = frame["latitude"].to_numpy(dtype="float64")
    lon = frame["longitude"].to_numpy(dtype="float64")
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()):
        raise AnalysisError("Summary cannot run: the dataset contains missing or non-finite coordinates.")
    if clusters is not None:
        _check_clusters_match_dataset(clusters, frame)
        _check_cluster_result(clusters)
    if density is not None:
        _check_density(density, len(frame))

    notes = list(STANDARD_NOTES)
    cluster_count = candidate_count = noise_share = None
    if clusters is None:
        notes.append("DBSCAN was not run: cluster_count, candidate_hotspot_count and noise_share are None.")
    else:
        cluster_count = len(clusters.clusters)
        candidate_count = sum(1 for c in clusters.clusters if c.is_candidate_hotspot)
        noise_share = clusters.noise_count / len(frame)
    if density is None:
        notes.append("KDE was not run.")

    comparison = None
    if clusters is not None and density is not None:
        comparison = compare_methods(clusters, density)
        if comparison.outside_grid_count:
            notes.append(
                f"{comparison.outside_grid_count} incident(s) lie outside the KDE grid extent and are "
                "excluded from the method comparison."
            )
    else:
        notes.append("Method comparison not computed: it needs both DBSCAN and KDE results.")

    return SpatialSummary(
        incident_count=len(frame),
        bounding_box=(float(lat.min()), float(lon.min()), float(lat.max()), float(lon.max())),
        mean_center=(float(lat.mean()), float(lon.mean())),
        cluster_count=cluster_count,
        candidate_hotspot_count=candidate_count,
        noise_share=noise_share,
        by_category=_category_counts(frame),
        notes=notes,
        method_comparison=comparison,
    )


def incidents_by_period(dataset: CleanDataset) -> dict[str, Any]:
    """Incident counts over time from the validated `incident_date` column.

    Uses the Stage 2 contract as-is: incident_date is datetime64 parsed from
    ISO 8601, with NaT for blank or unparseable dates. NaT rows are counted in
    `missing_dates` and excluded from the counts; nothing is imputed. Time-zone
    aware values are converted to UTC before grouping, including mixed offsets,
    which the validator leaves as an object column; naive values are used as-is.

    Period (deterministic, from the span between the earliest and latest date):
    <= 62 days -> "day", <= 1096 days -> "month", otherwise "year". Every period
    from the first to the last is listed, with 0 for periods without incidents.

    Returns {"column_present": bool, "period": str | None,
             "counts": DataFrame[period_start (datetime64), incident_count (int)],
             "dated_incidents": int, "missing_dates": int}.
    Raises AnalysisError for an unusable/empty dataset. The dataset is not mutated.
    """
    frame = dataset.frame
    if not dataset.report.is_usable or frame.empty:
        raise AnalysisError("Date counts cannot run: the dataset is unusable or has no accepted incidents.")
    empty = pd.DataFrame({"period_start": pd.Series(dtype="datetime64[ns]"), "incident_count": pd.Series(dtype="int64")})
    if "incident_date" not in frame.columns:
        return {"column_present": False, "period": None, "counts": empty, "dated_incidents": 0, "missing_dates": 0}

    column = frame["incident_date"]
    if pd.api.types.is_datetime64_any_dtype(column):
        dates = column.dt.tz_convert("UTC").dt.tz_localize(None) if column.dt.tz is not None else column
    else:
        # Mixed UTC offsets leave the validated column as objects (tz-aware datetimes or NaT):
        # convert every value to UTC; NaT stays NaT.
        dates = pd.to_datetime(column, utc=True, errors="coerce").dt.tz_localize(None)
    dated = dates.dropna()
    result = {"column_present": True, "period": None, "counts": empty,
              "dated_incidents": int(dated.size), "missing_dates": int(dates.isna().sum())}
    if dated.empty:
        return result

    span_days = (dated.max() - dated.min()).days
    period, freq = ("day", "D") if span_days <= 62 else ("month", "M") if span_days <= 1096 else ("year", "Y")
    periods = dated.dt.to_period(freq)
    full_range = pd.period_range(periods.min(), periods.max(), freq=freq)
    tally = periods.value_counts().reindex(full_range, fill_value=0)
    result["period"] = period
    result["counts"] = pd.DataFrame(
        {"period_start": full_range.to_timestamp(), "incident_count": tally.to_numpy(dtype="int64")}
    )
    return result


def compare_methods(clusters: ClusterResult, density: DensityResult) -> MethodComparison:
    """Point-based, descriptive comparison of DBSCAN labels with KDE high density.

    Eligibility: an incident is eligible when south <= lat <= north and
    west <= lon <= east for density.params["grid_extent"] (inclusive). Others
    are counted in outside_grid_count and never snapped to an edge node.
    Lookup: per axis, the nearest grid node; an exact midpoint goes to the
    lower (southern/western) node. High density: density[i, j] >= threshold.

    The table, totals and shares are defined in MethodComparison. The KDE is not
    refitted and no new threshold is introduced. Raises AnalysisError for
    inconsistent inputs; inputs are not mutated.
    """
    _check_cluster_result(clusters)
    frame = clusters.labeled_frame
    _check_density(density, len(frame))

    lat = frame["latitude"].to_numpy(dtype="float64")
    lon = frame["longitude"].to_numpy(dtype="float64")
    labels = frame[CLUSTER_LABEL_COLUMN].to_numpy()
    ext = density.params["grid_extent"]
    eligible = (lat >= ext["south"]) & (lat <= ext["north"]) & (lon >= ext["west"]) & (lon <= ext["east"])
    if density.params.get("grid_source") == "data_extent_padded" and not eligible.all():
        # A data-extent grid contains every point it was fitted on, by construction.
        raise AnalysisError(
            "Density result does not match the cluster result: some incidents lie outside a grid "
            "that was built from the data extent."
        )

    high = np.zeros(len(frame), dtype=bool)
    if eligible.any():
        rows = _nearest_node(density.grid_lat, lat[eligible])
        cols = _nearest_node(density.grid_lon, lon[eligible])
        high[eligible] = density.density[rows, cols] >= density.high_density_threshold

    clustered = labels != NOISE_LABEL
    c_high = int(np.count_nonzero(eligible & clustered & high))
    c_not = int(np.count_nonzero(eligible & clustered & ~high))
    n_high = int(np.count_nonzero(eligible & ~clustered & high))
    n_not = int(np.count_nonzero(eligible & ~clustered & ~high))

    per_cluster = []
    for summary in clusters.clusters:
        members = labels == summary.cluster_label
        member_eligible = int(np.count_nonzero(members & eligible))
        member_high = int(np.count_nonzero(members & eligible & high))
        per_cluster.append(
            ClusterOverlap(
                cluster_label=summary.cluster_label,
                incident_count=int(np.count_nonzero(members)),
                eligible_members=member_eligible,
                outside_grid_members=int(np.count_nonzero(members & ~eligible)),
                members_at_high_density=member_high,
                high_density_share=_share(member_high, member_eligible),
                is_candidate_hotspot=summary.is_candidate_hotspot,
            )
        )

    return MethodComparison(
        clustered_high=c_high,
        clustered_not_high=c_not,
        noise_high=n_high,
        noise_not_high=n_not,
        clustered_eligible=c_high + c_not,
        noise_eligible=n_high + n_not,
        high_density_eligible=c_high + n_high,
        not_high_density_eligible=c_not + n_not,
        eligible_count=c_high + c_not + n_high + n_not,
        outside_grid_count=int(np.count_nonzero(~eligible)),
        total_incidents=len(frame),
        clustered_high_share=_share(c_high, c_high + c_not),
        noise_high_share=_share(n_high, n_high + n_not),
        per_cluster=per_cluster,
        notes=list(COMPARISON_NOTES),
    )


# --- helpers -------------------------------------------------------------------


def _share(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _nearest_node(axis: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Index of the nearest node on an ascending axis; exact midpoints -> lower index."""
    if axis.size == 1:
        return np.zeros(values.size, dtype=np.intp)
    upper = np.clip(np.searchsorted(axis, values, side="left"), 1, axis.size - 1)
    lower = upper - 1
    choose_lower = (values - axis[lower]) <= (axis[upper] - values)
    return np.where(choose_lower, lower, upper)


def _category_counts(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for column in CATEGORY_COLUMNS:
        if column not in frame.columns:
            continue
        values = frame[column].astype(object).where(frame[column].notna(), MISSING_CATEGORY).map(str)
        tally = values.value_counts(sort=False)
        keys = sorted(k for k in tally.index if k != MISSING_CATEGORY)
        if MISSING_CATEGORY in tally.index:
            keys.append(MISSING_CATEGORY)
        counts[column] = {k: int(tally[k]) for k in keys}
    return counts


def _check_clusters_match_dataset(clusters: ClusterResult, frame: pd.DataFrame) -> None:
    labeled = clusters.labeled_frame
    if len(labeled) != len(frame) or not labeled.index.equals(frame.index):
        raise AnalysisError("Cluster result does not match the dataset: row index differs.")
    if not np.array_equal(labeled["incident_id"].to_numpy(), frame["incident_id"].to_numpy()):
        raise AnalysisError("Cluster result does not match the dataset: incident IDs differ.")
    for column in ("latitude", "longitude"):
        if not np.array_equal(labeled[column].to_numpy(dtype="float64"), frame[column].to_numpy(dtype="float64")):
            raise AnalysisError(f"Cluster result does not match the dataset: {column} values differ.")


def _check_cluster_result(clusters: ClusterResult) -> None:
    labeled = clusters.labeled_frame
    if CLUSTER_LABEL_COLUMN not in labeled.columns:
        raise AnalysisError(f"Cluster result has no {CLUSTER_LABEL_COLUMN!r} column.")
    raw = labeled[CLUSTER_LABEL_COLUMN]
    if not pd.api.types.is_integer_dtype(raw.dtype) or raw.isna().any():
        raise AnalysisError("Cluster labels must be integers.")
    labels = raw.to_numpy()
    if (labels < NOISE_LABEL).any():
        raise AnalysisError(f"Cluster labels must be >= {NOISE_LABEL}.")
    noise = int(np.count_nonzero(labels == NOISE_LABEL))
    if clusters.noise_count != noise:
        raise AnalysisError(f"Cluster result is inconsistent: noise_count {clusters.noise_count} != {noise} noise labels.")
    summary_labels = [c.cluster_label for c in clusters.clusters]
    if len(set(summary_labels)) != len(summary_labels):
        raise AnalysisError("Cluster result is inconsistent: duplicate cluster summaries.")
    if set(summary_labels) != set(np.unique(labels[labels != NOISE_LABEL]).tolist()):
        raise AnalysisError("Cluster result is inconsistent: summaries do not match the labels in labeled_frame.")
    for c in clusters.clusters:
        actual = int(np.count_nonzero(labels == c.cluster_label))
        if c.incident_count != actual:
            raise AnalysisError(
                f"Cluster result is inconsistent: cluster {c.cluster_label} reports {c.incident_count} "
                f"incidents but has {actual} labelled rows."
            )


def _check_density(density: DensityResult, n_rows: int) -> None:
    n_points = density.params.get("n_points")
    if not isinstance(n_points, Integral) or isinstance(n_points, bool) or n_points != n_rows:
        raise AnalysisError(f"Density result does not match the dataset: n_points {n_points!r} != {n_rows} incidents.")
    for name in ("grid_lat", "grid_lon"):
        axis = np.asarray(getattr(density, name))
        if axis.ndim != 1 or axis.size == 0 or not np.issubdtype(axis.dtype, np.number):
            raise AnalysisError(f"Density result has an invalid {name} axis.")
        if not np.isfinite(axis).all() or (axis.size > 1 and not (np.diff(axis) > 0).all()):
            raise AnalysisError(f"Density result {name} must be finite and strictly ascending.")
    values = np.asarray(density.density)
    if values.shape != (np.asarray(density.grid_lat).size, np.asarray(density.grid_lon).size):
        raise AnalysisError(
            f"Density array shape {values.shape} does not match axes "
            f"({np.asarray(density.grid_lat).size}, {np.asarray(density.grid_lon).size})."
        )
    if not np.isfinite(values).all() or (values < 0).any():
        raise AnalysisError("Density values must be finite and non-negative.")
    threshold = density.high_density_threshold
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float, np.floating)) or not math.isfinite(threshold):
        raise AnalysisError(f"high_density_threshold must be a finite number (got {threshold!r}).")
    ext = density.params.get("grid_extent")
    keys = ("south", "north", "west", "east")
    if not isinstance(ext, dict) or any(k not in ext for k in keys):
        raise AnalysisError("Density result params must include grid_extent with south, north, west and east.")
    if not all(isinstance(ext[k], (int, float)) and math.isfinite(ext[k]) for k in keys):
        raise AnalysisError("Density grid_extent values must be finite numbers.")
    if not (ext["south"] <= ext["north"] and ext["west"] <= ext["east"]):
        raise AnalysisError("Density grid_extent is inverted.")
    grid_lat, grid_lon = np.asarray(density.grid_lat), np.asarray(density.grid_lon)
    if not (grid_lat[0] <= ext["south"] and grid_lat[-1] >= ext["north"]
            and grid_lon[0] <= ext["west"] and grid_lon[-1] >= ext["east"]):
        raise AnalysisError("Density grid_extent is not covered by the grid axes.")
