"""Kernel density estimation. Owner: Member 3 (KDE and Spatial Density).

KernelDensity runs with metric="haversine" on radians; bandwidth is supplied in
metres and converted. The surface shows estimated relative density only — high
density is not proof of statistical significance.
"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np
from sklearn.neighbors import KernelDensity

from config.settings import EARTH_RADIUS_M, KDEParams, StudyArea
from modules.contracts import AnalysisError, CleanDataset, DensityResult

METRIC = "haversine"
ALGORITHM = "ball_tree"
# Local degree-per-metre factors (documented approximations, see DensityResult).
M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LON_AT_EQUATOR = 111_320.0
# Data-extent grids are padded by this many bandwidths on every side so the
# kernel tails of edge points are not cut off.
PAD_BANDWIDTHS = 3.0
# Largest grid evaluated. ~250k cells takes a few seconds; larger grids are
# refused (never silently coarsened) — raise grid_cell_m or set a study area.
MAX_GRID_CELLS = 250_000
# Beyond this latitude cos(lat) is too small for the local lon-step approximation.
MAX_ABS_GRID_LAT = 85.0
MAX_BANDWIDTH_M = math.pi * EARTH_RADIUS_M
DENSITY_UNITS = (
    "relative density score: estimated probability density per steradian of the sphere "
    "(integrates to ~1 over the surface); not an incident count and not a per-km2 rate"
)


def run_kde(
    dataset: CleanDataset,
    params: KDEParams,
    study_area: StudyArea | None = None,
    max_cells: int = MAX_GRID_CELLS,
) -> DensityResult:
    """Fit haversine KDE to all accepted incidents and evaluate it on a lat/lon grid.

    Coordinates: [lat, lon] in degrees, read by row POSITION, converted to
    radians; bandwidth_rad = bandwidth_m / EARTH_RADIUS_M. Every accepted
    incident is used; nothing is sampled or truncated.

    Grid: the study area box if given (points outside it still contribute to
    the estimate), otherwise the data bounding box padded by PAD_BANDWIDTHS
    bandwidths, clipped to legal ranges. Axes are ascending cell-centre values
    in degrees starting at the south/west edge, with steps
        lat_step = grid_cell_m / 110540
        lon_step = grid_cell_m / (111320 * cos(mean grid latitude)),
    so the last value is at or just beyond the north/east edge. density has shape
    (len(grid_lat), len(grid_lon)); density[i, j] is the value at
    (grid_lat[i], grid_lon[j]).

    Values: exp(KernelDensity.score_samples) unchanged — see DENSITY_UNITS. Each
    is the estimator evaluated at a grid point, not an amount in a cell: only
    sum(density * cell area in steradians) approximates the estimator's integral
    (1), and it is < 1 when the grid cuts off part of the mass; the plain sum
    of grid values is meaningless. They rank and compare locations; they are not
    counts, per-km2 rates, risk, or significance. high_density_threshold is the
    high_density_quantile of the grid values — a within-analysis classification
    that depends on the grid extent.

    Raises AnalysisError for an unusable/empty dataset, invalid parameters or
    coordinates, a grid above max_cells, or a grid beyond +/-85 degrees latitude.
    Deterministic; the input dataset is not mutated.
    """
    _validate(dataset, params, max_cells)
    lat = dataset.frame["latitude"].to_numpy(dtype="float64")
    lon = dataset.frame["longitude"].to_numpy(dtype="float64")
    bandwidth_m = float(params.bandwidth_m)
    cell_m = float(params.grid_cell_m)

    south, north, west, east = _grid_extent(lat, lon, bandwidth_m, study_area)
    mean_lat = (south + north) / 2
    if abs(south) > MAX_ABS_GRID_LAT or abs(north) > MAX_ABS_GRID_LAT:
        raise AnalysisError(
            f"KDE grid would extend beyond +/-{MAX_ABS_GRID_LAT} degrees latitude, where the "
            "local longitude-step approximation is not valid."
        )
    lat_step = cell_m / M_PER_DEG_LAT
    lon_step = cell_m / (M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians(mean_lat)))
    n_lat = math.ceil((north - south) / lat_step) + 1
    n_lon = math.ceil((east - west) / lon_step) + 1
    if n_lat * n_lon > max_cells:
        raise AnalysisError(
            f"KDE grid of {n_lat:,} x {n_lon:,} = {n_lat * n_lon:,} cells exceeds the limit of "
            f"{max_cells:,}. Increase grid_cell_m (now {cell_m:g} m) or set a smaller study area."
        )
    grid_lat = south + lat_step * np.arange(n_lat, dtype="float64")
    grid_lon = west + lon_step * np.arange(n_lon, dtype="float64")

    bandwidth_rad = bandwidth_m / EARTH_RADIUS_M
    kde = KernelDensity(bandwidth=bandwidth_rad, kernel=params.kernel, metric=METRIC, algorithm=ALGORITHM)
    kde.fit(np.radians(np.column_stack([lat, lon])))
    mesh_lat, mesh_lon = np.meshgrid(grid_lat, grid_lon, indexing="ij")
    query = np.radians(np.column_stack([mesh_lat.ravel(), mesh_lon.ravel()]))
    density = np.exp(kde.score_samples(query)).reshape(n_lat, n_lon)

    return DensityResult(
        grid_lat=grid_lat,
        grid_lon=grid_lon,
        density=density,
        high_density_threshold=float(np.quantile(density, params.high_density_quantile)),
        params={
            "bandwidth_m": bandwidth_m,
            "bandwidth_rad": bandwidth_rad,
            "kernel": params.kernel,
            "grid_cell_m": cell_m,
            "metric": METRIC,
            "algorithm": ALGORITHM,
            "lat_step_deg": lat_step,
            "lon_step_deg": lon_step,
            "grid_extent": {"south": south, "north": north, "west": west, "east": east},
            "grid_source": "study_area" if study_area is not None else "data_extent_padded",
            "high_density_quantile": float(params.high_density_quantile),
            "n_points": int(lat.size),
            "density_units": DENSITY_UNITS,
        },
    )


def _grid_extent(
    lat: np.ndarray, lon: np.ndarray, bandwidth_m: float, study_area: StudyArea | None
) -> tuple[float, float, float, float]:
    if study_area is not None:
        return study_area.min_lat, study_area.max_lat, study_area.min_lon, study_area.max_lon
    mean_lat = float((lat.min() + lat.max()) / 2)
    pad_lat = PAD_BANDWIDTHS * bandwidth_m / M_PER_DEG_LAT
    pad_lon = PAD_BANDWIDTHS * bandwidth_m / (M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians(min(abs(mean_lat), 89.0))))
    return (
        max(-90.0, float(lat.min()) - pad_lat),
        min(90.0, float(lat.max()) + pad_lat),
        max(-180.0, float(lon.min()) - pad_lon),
        min(180.0, float(lon.max()) + pad_lon),
    )


def _validate(dataset: CleanDataset, params: KDEParams, max_cells: int) -> None:
    if not dataset.report.is_usable or dataset.frame.empty:
        raise AnalysisError("KDE cannot run: the dataset is unusable or has no accepted incidents.")
    for name, limit in (("bandwidth_m", MAX_BANDWIDTH_M), ("grid_cell_m", MAX_BANDWIDTH_M)):
        value = getattr(params, name)
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
            raise AnalysisError(f"{name} must be a finite number of metres > 0 (got {value!r}).")
        if value > limit:
            raise AnalysisError(f"{name} must not exceed half the Earth's circumference, {limit!r} m; got {value!r}.")
    q = params.high_density_quantile
    if isinstance(q, bool) or not isinstance(q, Real) or not 0.0 < q < 1.0:
        raise AnalysisError(f"high_density_quantile must be strictly between 0 and 1 (got {q!r}).")
    if isinstance(max_cells, bool) or not isinstance(max_cells, int) or max_cells < 1:
        raise AnalysisError(f"max_cells must be an integer >= 1 (got {max_cells!r}).")
    lat = dataset.frame["latitude"].to_numpy(dtype="float64")
    lon = dataset.frame["longitude"].to_numpy(dtype="float64")
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()):
        raise AnalysisError("KDE cannot run: the dataset contains missing or non-finite coordinates.")
    if (np.abs(lat) > 90).any() or (np.abs(lon) > 180).any():
        raise AnalysisError("KDE cannot run: the dataset contains out-of-range coordinates.")
