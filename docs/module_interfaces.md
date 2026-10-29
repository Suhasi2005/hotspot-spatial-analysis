# Module Interfaces

The signatures exist in code now. Functions marked *done* are implemented and tested. All others still raise `NotImplementedError("Stage N: ...")`. Types come from `modules/contracts.py` and `config/settings.py`. Changing a signature needs team agreement and an update to this file in the same commit.

| Function | Input | Output | Errors | Stage |
|---|---|---|---|---|
| `data_manager.list_sample_datasets(directory)` | `Path` | `list[Path]` | — | 1 (done) |
| `data_manager.load_raw_dataset(source, source_name=None, max_rows=MAX_UPLOAD_ROWS)` | `Path \| BinaryIO` | `(DataFrame of str, str)` | `DataValidationError` (file-level rules in the dataset spec) | 2 (done) |
| `data_validator.validate_and_clean(raw, source_name, study_area=None)` | `DataFrame, str, StudyArea?` | `CleanDataset` (may be empty: `report.is_usable == False`) | `DataValidationError` **only** for a missing required column | 2 (done) |
| `data_validator.summarize_quality(report)` | `ValidationReport` | `DataFrame[severity, code, affected_rows, rows, message]` | — | 2 (done) |
| `app_controller.load_and_validate(source, source_name=None, study_area=None)` | file | `CleanDataset` | `DataValidationError` | 2 (done) |
| `dbscan_analysis.metres_to_radians(distance_m)` | `float` | `float` | — | 1 (done) |
| `dbscan_analysis.run_dbscan(dataset, params, criteria)` | `CleanDataset, DBSCANParams, CandidateHotspotCriteria` | `ClusterResult` | `AnalysisError` (unusable or empty dataset, invalid parameter, existing `cluster_label` column) | 4 (done) |
| `app_controller.cluster_dataset(dataset, config)` | `CleanDataset, AnalysisConfig` | `ClusterResult` | `AnalysisError` | 4 (done) |
| `density_analysis.run_kde(dataset, params, study_area=None, max_cells=MAX_GRID_CELLS)` | `CleanDataset, KDEParams, StudyArea?` | `DensityResult` | `AnalysisError` (unusable or empty dataset, invalid parameter or coordinate, grid too large, grid beyond ±85° latitude) | 5 (done) |
| `app_controller.estimate_density(dataset, config)` | `CleanDataset, AnalysisConfig` | `DensityResult` | `AnalysisError` | 5 (done) |
| `spatial_statistics.haversine_m(lat1, lon1, lat2, lon2)` | degrees (scalars) | metres | — | 4 (done, written by M2) |
| `spatial_statistics.summarize(dataset, clusters, density)` | `CleanDataset`; either result may be `None` | `SpatialSummary` | `AnalysisError` (unusable or empty dataset, results that don't match it, invalid results) | 6 (done) |
| `spatial_statistics.compare_methods(clusters, density)` | `ClusterResult, DensityResult` | `MethodComparison` | `AnalysisError` (invalid or inconsistent inputs) | 6 (done) |
| `map_visualization.build_incident_map(dataset, max_points=MAX_MAP_POINTS)` | `CleanDataset` | `folium.Map` | `AnalysisError` if unusable or empty | 3 (done) |
| `map_visualization.incident_marker_records(dataset, max_points=MAX_MAP_POINTS)` | `CleanDataset` | `list[dict]` with keys `incident_id, lat, lon, source_row, tooltip, popup_html` | `AnalysisError` if unusable or empty | 3 (done) |
| `map_visualization.build_cluster_map(result)` | `ClusterResult` | `folium.Map` | — | 7 |
| `map_visualization.build_density_map(result)` | `DensityResult` | `folium.Map` | — | 7 |
| `app_controller.run_analysis(source, config, source_name=None, persist=True)` | file + `AnalysisConfig` | `AnalysisRun` | propagates the errors above | 8 |
| `database.init_db / save_run / list_runs` | `AnalysisRun`, `Path` | `None` / `list[dict]` | `sqlite3.Error` (not swallowed) | 8 |
| `report_generator.export_csv(run, out_dir)` | `AnalysisRun` | `list[Path]` | `OSError` | 9 |
| `report_generator.export_pdf(run, out_dir)` | `AnalysisRun` | `Path` | `OSError` | 9 |

## Contract decisions (Stage 1 audit)
- **Duplicate IDs:** the first occurrence is kept; later ones are rejected as `DUPLICATE_ID`, and blank IDs as `MISSING_ID`. This happens only in `validate_and_clean`, and no other module de-duplicates. See `dataset_specification.md` → *Incident ID rules*.
- **Unusable datasets:** zero valid rows returns `report.is_usable == False` and does not raise. `app_controller.run_analysis` must check this and stop before DBSCAN or KDE, returning an `AnalysisRun` whose `clusters`, `density` and `summary` are `None`.
- **KDE grid:** `density[i, j]` corresponds to `(grid_lat[i], grid_lon[j])`. Degree steps come from local approximations. See the `DensityResult` docstring.
- **Cluster centroid:** the mean of lat and the mean of lon in degrees; `radius_m` is the maximum haversine distance to a member. Valid for compact study areas. See the `ClusterSummary` docstring.
- **`haversine_m` ownership:** it lives in `spatial_statistics.py`. Member 2 implements it in Stage 4, and `dbscan_analysis` imports it from there through this public signature. It is deliberately not moved. Member 2 coordinates edits to that function with Members 3 and 5.

## Stage 2 additions (compatible, additive)
- **`app_controller.load_and_validate`:** a new function. The UI may call only the controller, so Stage 2 needed a load-and-validate entry point before `run_analysis` exists. `run_analysis` should reuse it in Stage 8.
- **`load_raw_dataset` takes an optional `max_rows`:** the default comes from config, so existing calls are unchanged.
- **New issue code `NON_FINITE_COORDINATE`:** for `inf` coordinates, which no existing code covered.
- **Clean frame index:** `CleanDataset.frame` keeps the **source row index**, not a renumbered `0..n-1`. Downstream modules must not assume a `RangeIndex`. Use positional operations (`.to_numpy()`, `.iloc`) where needed.

## Stage 3 additions (compatible, additive)
- **Empty or unusable input to the incident map raises `AnalysisError`.** The contract didn't specify this case before. An empty map would need a hard-coded fallback location, which the project avoids. The UI checks `is_usable` first and shows a message instead. `run_dbscan` follows the same rule in Stage 4.
- **`max_points` (default `MAX_MAP_POINTS` = 5,000)** caps how many markers are drawn, taking the first N rows in file order. It is a rendering limit only: the dataset is not changed. `max_points=None` draws every row.
  - When the cap applies, the UI says that only the first 5,000 are displayed and that this is **not a representative sample**: file order may follow time or place, so the drawn points may not reflect where incidents concentrate.
  - Better sampling or aggregation is deferred.
- **`incident_marker_records`** is the plain marker data the map is built from. It exists so tests and later layers can check positions and IDs without parsing HTML.
- **Marker rules:**
  - Coordinates are read **by position** (`to_numpy()` / `iloc`).
  - The frame's index label is carried only as `source_row`, for tracing back to the file.
  - Every user-supplied value in tooltips and popups is HTML-escaped.
  - Popups show only the optional columns that exist and are non-blank.
- **View:** the initial centre is the midpoint of the data's bounding box. For more than one distinct location the map fits that box; a single location is centred at zoom 15.
- **Determinism:** marker order, positions and popup text are deterministic for a fixed input. Folium's internal element IDs are random and are not part of the contract.

## Stage 4 decisions (DBSCAN)
- **Distance convention (the only one):** sklearn `DBSCAN(metric="haversine", algorithm="ball_tree")` on `[lat, lon]` in radians, built by row position.
  - `eps_rad = eps_m / 6,371,008.8`.
  - `haversine_m` uses the same sphere, so `radius_m` and `eps_m` are directly comparable.
- **`min_samples`** counts the point itself (sklearn semantics). `min_samples=1` makes every point a cluster.
- **Parameter validation inside `run_dbscan`** (raises `AnalysisError`). This closes gaps that `DBSCANParams` and `CandidateHotspotCriteria` construction leave open; the shared config is unchanged.
  - `eps_m` must be a finite real number > 0 and ≤ `MAX_EPS_M = π × 6,371,008.8` m, half the circumference of the mean-radius sphere (the antipodal distance). The comparison is done in metres, with no tolerance: the boundary value itself is accepted, and the next representable float above it is rejected. NaN, ±inf and bools are rejected.
  - `min_samples` and `min_incidents` must be integers ≥ 1. Floats and bools are rejected; NumPy integers are accepted.
  - The coordinates are re-checked as finite and in range, in case a `CleanDataset` was built by hand.
- **Labels are attached by position.**
  - `labeled_frame` is a copy of `dataset.frame` with the same rows, order and **source index**, plus `cluster_label`. Noise is `-1`.
  - A source column already named `cluster_label` is refused, never overwritten.
  - Any cluster label traces back to its file row through the frame's index.
- **Summaries.**
  - One `ClusterSummary` per real cluster, in ascending label order. There is none for noise; noise is counted in `noise_count`.
  - Labels are arbitrary IDs, not ranks.
  - Centroid = mean lat and mean lon (degrees). `radius_m` = largest `haversine_m` from the centroid to a member.
- **Candidate hotspot:** `incident_count >= criteria.min_incidents` (the threshold counts as met). This is a size rule only and implies no statistical significance. `min_density_per_km2` is **ignored** until an area calculation is agreed. The default `min_incidents = 10` is still a placeholder awaiting justification from real data.
- **Edge cases.**
  - An empty or unusable dataset raises `AnalysisError`.
  - Fewer points than `min_samples` is **not** an error: every point is noise and `clusters == []`.
- **`params` records exactly what was passed to sklearn:** `eps_m`, `eps_rad`, `min_samples` (a Python `int`), `metric`, `algorithm`.
- **`app_controller.cluster_dataset`** is a small additive entry point. It checks `is_usable`, then calls `run_dbscan` with `config.dbscan` and `config.hotspot`. The UI doesn't call it yet; the clustering page is Stage 7.

## Stage 5 decisions (KDE)
- **Coordinate convention (unchanged from Stage 1, now implemented):**
  - `KernelDensity(metric="haversine", algorithm="ball_tree")` on `[lat, lon]` in radians, built by row position. This is a spherical KDE: no planar KDE on raw degrees and **no projected CRS**.
  - `bandwidth_rad = bandwidth_m / 6,371,008.8`, the same sphere as DBSCAN.
  - A projected CRS is still reserved for future per-km² measures. None is chosen, and Stage 5 needs none.
- **Every accepted incident is used.** There is no sampling or truncation, and repeated coordinates are kept.
- **Grid extent:**
  - With a `study_area`, the grid is exactly that box. Points outside the box still contribute to the estimate.
  - Otherwise it is the data bounding box padded by 3 bandwidths on each side, clipped to ±90 / ±180.
  - A grid reaching beyond ±85° latitude is refused, because the longitude-step approximation breaks down there.
  - A box that crosses the 180° meridian is not supported.
- **Grid axes:**
  - Ascending float64 degree values at which the density is evaluated.
  - They start exactly at the south and west edges, with steps `lat_step = cell_m/110540` and `lon_step = cell_m/(111320·cos φ̄)`, where φ̄ is the grid's mean latitude.
  - The last value lies at, or less than one step beyond, the north and east edges.
  - Steps are recorded in `params` as `lat_step_deg` and `lon_step_deg`.
- **Orientation:** `density.shape == (len(grid_lat), len(grid_lon))`, and `density[i, j]` is the value at `(grid_lat[i], grid_lon[j])`. Rows follow latitude, columns follow longitude. Tested against an independent estimator.
- **Units of `density`:**
  - The values are `exp(score_samples)` unchanged: an **estimated probability density per steradian** of the sphere. Each value is the estimator evaluated at one grid point; it is **not** an amount contained in a cell.
  - The estimator itself integrates to 1 over the sphere, valid while the bandwidth is far smaller than the Earth's radius.
  - On the grid, only the **area-weighted** sum `Σ density × cell area (sr)` approximates that integral. It was tested to within 0.5% when the grid covers the distribution.
  - It falls **below 1** when the grid cuts off part of the distribution. With the 3-bandwidth padding about 0.1–0.2% is outside, which is why the synthetic run gave 0.9987. With a study area, any amount can be outside.
  - The **plain sum of the grid values has no meaning**: it changes with the cell size. Neither sum is a count of incidents.
  - They are labelled **relative density scores** (`params["density_units"]`).
  - They are **not** incident counts, **not** incidents per km², and **not** risk adjusted for exposure (traffic, population or time). A high value is not statistical significance.
  - Repeated coordinates add weight relative to other points. A dataset of N copies of one point gives exactly the same surface as one point.
- **`high_density_threshold`** = `np.quantile(density, high_density_quantile)` over the grid cells.
  - It is a **within-analysis classification only**: "high-density" means among the highest values of this grid.
  - It depends on the grid extent, so it is not comparable across runs with different extents or datasets.
  - It is not an absolute standard, and it is unrelated to DBSCAN's `min_incidents`.
- **Validation (raises `AnalysisError`):**
  - `bandwidth_m` and `grid_cell_m` must be finite real numbers > 0 and ≤ π·R. NaN, ±inf and bools are rejected; `KDEParams` construction leaves these open.
  - `high_density_quantile` must be strictly between 0 and 1.
  - The coordinates are re-checked as finite and in range.
- **Memory and time limit:** `max_cells` (default `MAX_GRID_CELLS` = 250,000) is checked **before** any allocation. Larger grids are refused with a message to raise `grid_cell_m` or set a study area, never silently coarsened. A measured reference point: 1.86M cells took about 18 s, and 77k cells under 1 s.
- **`params`** records `bandwidth_m`, `bandwidth_rad`, `kernel`, `grid_cell_m`, `metric`, `algorithm`, `lat_step_deg`, `lon_step_deg`, `grid_extent`, `grid_source`, `high_density_quantile`, `n_points` and `density_units`.
- **`app_controller.estimate_density`** is additive. It checks `is_usable`, then calls `run_kde(dataset, config.kde, config.study_area)`. There is no UI yet; the heatmap is Stage 7.
- **Other regions:** nothing is tied to one city. Very large or high-latitude areas are limited by the cell cap and the ±85° rule. For those, set a `study_area` and a coarser `grid_cell_m`.

## Stage 6 decisions (spatial statistics and method comparison)
### Contract changes (approved)
- **New `ClusterOverlap` and `MethodComparison` dataclasses**, plain `@dataclass` like the other contracts. `SpatialSummary` gains an optional `method_comparison: MethodComparison | None = None`, so existing constructors keep working.
- **Three `SpatialSummary` fields are now optional:** `cluster_count: int | None`, `candidate_hotspot_count: int | None` and `noise_share: float | None`.
  - `None` means DBSCAN was **not run**.
  - `0` or `0.0` means it ran and the value is zero.

### `summarize(dataset, clusters, density) -> SpatialSummary`
- **Dataset-level values**, from `dataset.frame` by position:
  - `incident_count`;
  - `bounding_box = (min_lat, min_lon, max_lat, max_lon)`;
  - `mean_center = (mean lat, mean lon)`, arithmetic means in degrees. This suits city-scale data and is **not** valid across the 180° meridian.
- **From the cluster result**, all `None` without one:
  - `cluster_count = len(clusters.clusters)`;
  - `candidate_hotspot_count` = clusters with `is_candidate_hotspot`;
  - `noise_share = (rows with cluster_label == -1) / accepted incidents`.
- **`by_category`** counts `severity` and `incident_type` only when those columns exist. Keys are sorted, and missing values are counted last under `"(missing)"`. There is no date or location aggregation.
- **`method_comparison`** is `compare_methods(clusters, density)` only when **both** results are given; otherwise it is `None`.
- **`notes`** always state that:
  - clusters and high-density locations are descriptive;
  - KDE values are relative density scores, not counts or per-km² rates;
  - candidate hotspots follow the DBSCAN `min_incidents` rule only;
  - no significance test was run;
  - the mean centre has the 180° limitation.

  They also say which analyses weren't run and how many incidents fell outside the KDE grid.

### `compare_methods(clusters, density) -> MethodComparison` (point-based)
- **Eligibility:** an incident is eligible when `south ≤ lat ≤ north` and `west ≤ lon ≤ east` for `density.params["grid_extent"]`. The bounds are inclusive.
  - Other incidents are counted in `outside_grid_count` and are **never snapped** to an edge node.
  - The extent, not the axis span, decides eligibility. The last axis node may lie beyond the north and east edges.
- **Lookup:** for each eligible incident, take the nearest latitude node and the nearest longitude node, and read the existing `density[row, col]`.
  - A value exactly midway between two nodes goes to the **lower** (southern or western) node.
  - The match is an approximation of up to half a cell per axis.
  - KDE is not refitted and no new threshold is introduced.
- **High density:** `density[row, col] >= high_density_threshold`, so a value equal to the threshold counts as high.
- **2×2 table over eligible incidents:**

  | | KDE high | KDE not high | row total |
  |---|---|---|---|
  | DBSCAN clustered (label ≠ −1) | `clustered_high` | `clustered_not_high` | `clustered_eligible` |
  | DBSCAN noise (label = −1) | `noise_high` | `noise_not_high` | `noise_eligible` |
  | column total | `high_density_eligible` | `not_high_density_eligible` | `eligible_count` |

  `total_incidents = eligible_count + outside_grid_count`. Every eligible incident is in exactly one cell.
- **Shares** (`None` when the denominator is 0, never 0):
  - `clustered_high_share = clustered_high / clustered_eligible`;
  - `noise_high_share = noise_high / noise_eligible`.
- **`per_cluster`:** one `ClusterOverlap` per DBSCAN cluster, in `clusters.clusters` order, with:
  - `incident_count = eligible_members + outside_grid_members`;
  - `members_at_high_density`;
  - `high_density_share = members_at_high_density / eligible_members`, or `None` when there are none;
  - `is_candidate_hotspot`, copied from the DBSCAN summary.

  `Σ members_at_high_density == clustered_high`.
- **The table is descriptive.** It is not a test of statistical association, not significance, and not an independent validation of either method. No chi-square, Getis-Ord or other test is run.

### Validation (raises `AnalysisError`; inputs are never changed)
- **Dataset:** unusable or empty, or non-finite coordinates.
- **Cluster result against the dataset:**
  - the index must be equal and in the same order;
  - `incident_id`, `latitude` and `longitude` must be equal by position.
- **Cluster result internally:**
  - integer labels ≥ −1;
  - `noise_count` equals the number of `-1` labels;
  - one summary per non-noise label, with no duplicates or missing ones;
  - each summary's `incident_count` equals its labelled rows.
- **Density result:**
  - `params["n_points"]` must be an integer equal to the incident count;
  - each axis must be 1-D, finite and strictly ascending;
  - the density shape must equal `(len(grid_lat), len(grid_lon))`;
  - values must be finite and ≥ 0, and the threshold finite;
  - `params["grid_extent"]` must exist with finite south, north, west and east, must not be inverted, and must be covered by the axes.
- **Both results together:** a grid with `grid_source == "data_extent_padded"` contains every point it was fitted on by construction. Any incident outside such a grid is therefore reported as a mismatch, not as outside the grid.
- **Limitation:** the KDE result carries no incident IDs, so a matching `n_points` plus these extent checks cannot *prove* the KDE came from the same dataset. Provenance or hashing is out of scope for Stage 6.

## Invariants every implementer must keep
- Input frames are never mutated. Return new frames.
- `labeled_frame` keeps every clean row, in the same order, with `cluster_label` added.
- Every unit is stated: metres for distances, degrees for stored coordinates, radians only inside the sklearn calls.
- `params` dicts in results record exactly what was passed to sklearn, so a run can be reproduced.

## Working independently
Each owner codes against hand-built contract objects, for example a `CleanDataset` built from the synthetic fixture in `tests/conftest.py`. Nobody waits on upstream code. Integration (Stage 8) then only has to wire up functions that are already tested.
