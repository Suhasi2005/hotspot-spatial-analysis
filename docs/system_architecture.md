# System Architecture

**Status: implemented (Stages 1–9).** Every module below exists and is covered by tests.
- The UI calls the controller (`load_and_validate`, `cluster_dataset`, `estimate_density`, `summarize_results`, `record_run`, `generate_reports`) and the map builders.
- `run_analysis` runs the whole pipeline without the UI.
- Exact interfaces and decisions: `module_interfaces.md`.

## High-level view
```
app.py (navigation)
  └─ modules/dashboard.py           UI only (Streamlit)
       └─ modules/app_controller.py  workflow orchestration (no Streamlit)
            ├─ data_manager          load CSV
            ├─ data_validator        validate + clean  -> CleanDataset
            ├─ dbscan_analysis       clusters          -> ClusterResult
            ├─ density_analysis      KDE grid          -> DensityResult
            ├─ spatial_statistics    summary           -> SpatialSummary
            ├─ database              SQLite history
            └─ report_generator      CSV / PDF
       └─ modules/map_visualization.py  folium.Map builders (no Streamlit)
config/settings.py   paths, schema, parameter dataclasses
modules/contracts.py shared dataclasses + exceptions
```

## Module responsibilities
| Module | Owner | Responsibility |
|---|---|---|
| `config/settings.py` | All | Paths from the project root, schema constants, validated parameter dataclasses |
| `contracts.py` | All (team-agreed) | Data types passed between modules |
| `data_manager.py` | M1 | Read CSV from disk or upload without changing values |
| `data_validator.py` | M1 | Schema checks, coordinate rules, quality report |
| `dbscan_analysis.py` | M2 | Haversine DBSCAN, cluster summaries, candidate-hotspot flag |
| `density_analysis.py` | M3 | Haversine KDE on a grid, high-density threshold |
| `spatial_statistics.py` | M3/M5 | Distances, descriptive statistics, method comparison |
| `map_visualization.py` | M4 | Folium layers |
| `dashboard.py` | M4 | Streamlit pages, filters, Plotly charts |
| `app_controller.py` | M5 | Runs the pipeline; the UI calls only this |
| `database.py` | M5 | `sqlite3` run history |
| `report_generator.py` | M5 | CSV + ReportLab PDF |

## Data flow
Raw CSV → `load_raw_dataset` → `validate_and_clean` → `CleanDataset` → (`run_dbscan`, `run_kde`, run independently) → `summarize` → `AnalysisRun` → dashboard / `save_run` / exports.

## Technology choices
Streamlit (fast UI, no separate backend), pandas/NumPy, GeoPandas/Shapely (study-area geometry, CRS handling), scikit-learn (`DBSCAN` and `KernelDensity`, both of which support `metric="haversine"` with a ball tree), Folium + streamlit-folium, Plotly, stdlib `sqlite3`, ReportLab, pytest.

## Geospatial processing principles
1. Data is stored as WGS 84 (EPSG:4326) decimal degrees and is never used as Cartesian x/y for distances.
2. DBSCAN and KDE take `[lat, lon]` **in radians** with `metric="haversine"`. Parameters are given in metres and converted with `value_m / EARTH_RADIUS_M` (6,371,008.8 m). The spherical model's error compared with the WGS 84 ellipsoid is well under 1% at city scale, which is acceptable for this purpose.
3. KDE bandwidth is stated in metres in the UI and stored with the run in both metres and radians. Density values are relative and are not incident counts.
   - The evaluation grid uses lat/lon axes, and `density[i, j]` corresponds to `(grid_lat[i], grid_lon[j])`.
   - The cell size in metres is converted to degrees approximately: `lat_step ≈ m/110540` and `lon_step ≈ m/(111320·cos φ̄)`, where φ̄ is the mean latitude of the grid.
   - Cells are therefore only nominally square.
4. Folium takes `[lat, lon]` in degrees. GeoJSON uses `[lon, lat]`. Map builders own this conversion.
5. Area-based measures, such as density per km², use a projected CRS chosen per study area (for example a UTM zone) via GeoPandas `estimate_utm_crs()`.
6. Terminology:
   - **Cluster**: a DBSCAN density-connected group.
   - **High-density area**: a KDE cell at or above the configured quantile.
   - **Candidate hotspot**: a cluster that meets the documented criteria.

   None of these is a statistically significant hotspot. That needs a formal test, which is not in scope.

## Integration approach
- Modules exchange only the dataclasses in `contracts.py`.
- The UI depends on `app_controller` and `map_visualization`. Analytical modules never import Streamlit; a test enforces this.
- Each module can be developed against synthetic fixtures before upstream modules are finished.
