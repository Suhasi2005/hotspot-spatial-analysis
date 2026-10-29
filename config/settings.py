"""Central configuration: paths, schema names and default analysis parameters.

Every path is derived from PROJECT_ROOT so the project runs from any checkout
location. Environment variables (see .env.example) may override a few values;
they are read from the process environment only — no secrets live here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = PROJECT_ROOT / "data"
SAMPLE_DATA_DIR: Path = DATA_DIR / "sample"
PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"
REPORTS_DIR: Path = PROJECT_ROOT / os.environ.get("HOTSPOT_REPORTS_DIR", "reports")
DB_PATH: Path = PROJECT_ROOT / os.environ.get(
    "HOTSPOT_DB_PATH", "data/processed/analysis_history.sqlite3"
)
LOG_LEVEL: str = os.environ.get("HOTSPOT_LOG_LEVEL", "INFO").upper()

# --- Geodesy -----------------------------------------------------------------
# Mean Earth radius (IUGG). Used to convert metres <-> radians for haversine.
EARTH_RADIUS_M: float = 6_371_008.8
# Coordinates are always stored as WGS 84 decimal degrees.
SOURCE_CRS: str = "EPSG:4326"

# --- Shared data contract (see docs/dataset_specification.md) ----------------
REQUIRED_COLUMNS: tuple[str, ...] = ("incident_id", "latitude", "longitude")
OPTIONAL_COLUMNS: tuple[str, ...] = (
    "incident_date",
    "incident_type",
    "location_name",
    "severity",
)
LATITUDE_RANGE: tuple[float, float] = (-90.0, 90.0)
LONGITUDE_RANGE: tuple[float, float] = (-180.0, 180.0)
SUPPORTED_UPLOAD_EXTENSIONS: tuple[str, ...] = (".csv",)
MAX_UPLOAD_ROWS: int = 500_000


@dataclass(frozen=True)
class StudyArea:
    """Bounding box of the area under analysis (WGS 84 degrees).

    `None` means "no study-area filter". Points outside a configured box are
    reported by validation, not silently dropped.
    """

    name: str
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def __post_init__(self) -> None:
        if not (LATITUDE_RANGE[0] <= self.min_lat < self.max_lat <= LATITUDE_RANGE[1]):
            raise ValueError(f"Invalid latitude bounds for study area {self.name!r}")
        if not (LONGITUDE_RANGE[0] <= self.min_lon < self.max_lon <= LONGITUDE_RANGE[1]):
            raise ValueError(f"Invalid longitude bounds for study area {self.name!r}")


@dataclass(frozen=True)
class DBSCANParams:
    """DBSCAN parameters in human units.

    eps_m is a ground distance in metres. The DBSCAN module converts it to
    radians (eps_m / EARTH_RADIUS_M) and runs with metric="haversine" on
    [lat, lon] in radians.
    """

    eps_m: float = 250.0
    min_samples: int = 5

    def __post_init__(self) -> None:
        if self.eps_m <= 0:
            raise ValueError("eps_m must be > 0")
        if self.min_samples < 1:
            raise ValueError("min_samples must be >= 1")


@dataclass(frozen=True)
class KDEParams:
    """Kernel density parameters.

    bandwidth_m is in metres; converted to radians for the haversine kernel.
    grid_cell_m sets the resolution of the evaluated density surface.
    high_density_quantile marks cells at/above this quantile as high density.
    """

    bandwidth_m: float = 300.0
    kernel: str = "gaussian"
    grid_cell_m: float = 100.0
    high_density_quantile: float = 0.95

    def __post_init__(self) -> None:
        if self.bandwidth_m <= 0 or self.grid_cell_m <= 0:
            raise ValueError("bandwidth_m and grid_cell_m must be > 0")
        if not 0.0 < self.high_density_quantile < 1.0:
            raise ValueError("high_density_quantile must be in (0, 1)")
        # haversine metric in sklearn KernelDensity supports these kernels only
        if self.kernel not in ("gaussian", "tophat", "epanechnikov", "exponential", "linear", "cosine"):
            raise ValueError(f"Unsupported kernel {self.kernel!r}")


@dataclass(frozen=True)
class CandidateHotspotCriteria:
    """Documented rules for promoting a DBSCAN cluster to a *candidate* hotspot.

    A candidate hotspot is NOT a statistically significant hotspot. These
    thresholds are placeholders to be justified by Member 2 in Stage 4.
    """

    min_incidents: int = 10
    min_density_per_km2: float | None = None


@dataclass(frozen=True)
class AnalysisConfig:
    """Bundle of every parameter that affects an analysis run (stored in history)."""

    dbscan: DBSCANParams = field(default_factory=DBSCANParams)
    kde: KDEParams = field(default_factory=KDEParams)
    hotspot: CandidateHotspotCriteria = field(default_factory=CandidateHotspotCriteria)
    study_area: StudyArea | None = None
    random_seed: int = 42


DEFAULT_ANALYSIS_CONFIG = AnalysisConfig()
