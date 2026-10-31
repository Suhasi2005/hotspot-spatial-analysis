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
| `map_visualization.build_cluster_map(result, max_points=MAX_MAP_POINTS, point_mask=None, cluster_labels=None)` | `ClusterResult`, optional positional boolean mask, optional set of labels | `folium.Map` | `AnalysisError` (empty or inconsistent result, bad mask) | 7 (done) |
| `map_visualization.cluster_marker_records(result, max_points=MAX_MAP_POINTS, point_mask=None)` | `ClusterResult` | `list[dict]` (incident-marker keys + `cluster_label`) | `AnalysisError` | 7 (done) |
| `map_visualization.build_density_map(result)` | `DensityResult` | `folium.Map` | `AnalysisError` (invalid result, uneven axes) | 7 (done) |
| `map_visualization.density_overlay_bounds(result)` | `DensityResult` | `[[south, west], [north, east]]` cell edges | `AnalysisError` | 7 (done) |
| `map_visualization.density_overlay_rgba(result, threshold_mask=False)` | `DensityResult` | `uint8` array `(len(grid_lat), len(grid_lon), 4)`, north row first | `AnalysisError` | 7 (done) |
| `spatial_statistics.incidents_by_period(dataset)` | `CleanDataset` | `dict` (see Stage 7 decisions) | `AnalysisError` (unusable or empty dataset) | 7 (done) |
| `app_controller.summarize_results(dataset, clusters, density)` | as `summarize` | `SpatialSummary` | as `summarize` | 7 (done) |
| `app_controller.run_analysis(source, config, source_name=None, persist=True, *, db_path=DB_PATH)` | file + `AnalysisConfig` | `AnalysisRun` | propagates `DataValidationError`, `AnalysisError`, `sqlite3.Error`, `OSError`; failed runs are not saved | 8 |
| `app_controller.record_run(dataset, config, clusters, density, summary, *, db_path=DB_PATH)` | already computed results | `AnalysisRun` (saved) | `AnalysisError` (partial or mismatched results); storage errors propagate | 8 |
| `database.init_db(db_path) / save_run(run, db_path) / list_runs(limit=50, db_path)` | `AnalysisRun`, `Path` | `None` / `None` / `list[dict]` | `sqlite3.Error`, `OSError`, `ValueError` (not swallowed) | 8 |
| `database.config_to_json(config) / config_from_json(text)` | `AnalysisConfig` / `str` | `str` / `AnalysisConfig` | `ValueError` (NaN, unknown schema version) | 8 |
| `report_generator.export_csv(run, out_dir)` | complete usable `AnalysisRun`, existing folder | `[incidents.csv, clusters.csv]` | `AnalysisError` (ineligible run, column clash), `FileExistsError`, `OSError` | 9 (done) |
| `report_generator.export_pdf(run, out_dir)` | complete usable `AnalysisRun`, existing folder | `report.pdf` | `AnalysisError`, `FileExistsError`, `OSError` | 9 (done) |
| `report_generator.report_sections(run)` / `pdf_markup(text)` | `AnalysisRun` / any value | `list[ReportSection]` (plain text) / escaped markup | `AnalysisError` | 9 (done) |
| `database.set_report_paths(run_id, paths, db_path, *, reports_dir=REPORTS_DIR)` | paths inside `reports_dir` | stored relative strings | `LookupError` (unknown run), `ValueError` (already set, outside the folder, empty list) | 9 (done) |
| `database.get_run(run_id, db_path)` / `resolve_report_path(stored, reports_dir)` | run ID / stored string | `dict` or `None` / absolute `Path` | `ValueError` (traversal, absolute path) | 9 (done) |
| `app_controller.generate_reports(run, out_dir=REPORTS_DIR, *, db_path=DB_PATH)` | saved complete `AnalysisRun` | final `list[Path]` | `AnalysisError`, `FileExistsError`, `OSError`, `sqlite3.Error` | 9 (done) |

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

## Stage 7 decisions (cluster and density maps, dashboard)
### Cluster map
- **Points:**
  - Read by position from `labeled_frame`. Cluster members use `CLUSTER_PALETTE[label % 10]`, ten distinguishable colours that are the same every run; with more than ten clusters the colours repeat, so the label also appears in popups.
  - Noise (`-1`) is drawn as smaller dark-grey markers (`#616161`, radius 4 against 5 for cluster members), so they stay visible on the basemap.
  - Popups reuse the escaped incident-popup format, plus a "DBSCAN: cluster N | noise" line. The incident map's own output is unchanged.
- **Point cap:** at most `MAX_MAP_POINTS` (5,000) markers. The cap is applied **after** the display mask and **before** markers are built: the first rows in file order. The dashboard warns that the drawn points are **not a representative sample**.
- **Circles:**
  - One `folium.Circle` per cluster, at the reported centroid with the reported `radius_m` in metres. They are always drawn regardless of the point cap; only the "candidate hotspots only" filter can hide non-candidate circles.
  - Nothing is recomputed from the DBSCAN result.
  - Candidate hotspots get a thick black outline and the tooltip "Candidate hotspot — size rule only (not statistical significance)".
  - A one-point cluster has `radius_m = 0`, so its circle has no visible size; its point is still drawn. Compact clusters (tens of metres) look like dots at city zoom and become visible when zoomed in. Circles sit under the points so the points' popups stay clickable.
- **Layer controls** sit top-left on both maps, so they don't cover the density legend.

### Density map
- **What is drawn:** the existing KDE grid as an `ImageOverlay`. There is **no** `HeatMap` plugin and no new estimator.
- **`density_overlay_bounds`:** each node is the centre of a cell one step wide, so the bounds run from half a step before the first node to half a step after the last node: `[[grid_lat[0] − Δlat/2, grid_lon[0] − Δlon/2], [grid_lat[-1] + Δlat/2, grid_lon[-1] + Δlon/2]]`. The steps come from the axes, or from `params` for a one-node axis. Latitude is clipped to ±85.0511, the Web Mercator limit. Unevenly spaced axes are rejected.
- **Orientation (`density_overlay_rgba`):**
  - Image row 0 is the **north** edge, and image column `c` is grid column `c`, because longitude is linear in Web Mercator.
  - Leaflet stretches an overlay linearly in **Web Mercator**, but the KDE rows are evenly spaced in latitude. So each image row is placed at its centre's Mercator position, converted back to latitude, and filled from the nearest grid row (an exact tie goes to the southern row). The image is then passed with `mercator_project=False`.
  - At city scale this equals a simple north-up flip. Over large latitude ranges it does not, which is tested over 0–60°.
- **Colour:**
  - `density / grid maximum`, interpolated linearly over 5 colour stops. The legend is the `LinearColormap` with ticks from 0 to 1, captioned "Relative density score — not incident counts or incidents/km²." The Density page adds that colours are scaled to this grid's maximum.
  - Cells below 1% of the maximum are fully transparent and the rest are 65% opaque. This is rendering only; the `DensityResult` is never changed.
- **High-density layer:** a separate overlay that can be switched on and off (hidden by default), drawn where `density >= high_density_threshold`. It is labelled as relative to this analysis and grid only.
- **Limitations:**
  - Each cell shows the estimate at its node, not an average over the cell.
  - Cells are only approximately square.
  - Validation reuses the Stage 6 checks (`_check_density`, `_check_cluster_result`), so a `DensityResult` must carry `params["n_points"]` and `grid_extent`.

### Dashboard
- **Sidebar parameters** (defaults from `DEFAULT_ANALYSIS_CONFIG`): `eps_m`, `min_samples`, `min_incidents`, `bandwidth_m`, `grid_cell_m`, `high_density_quantile`. They are validated by the existing dataclasses; an invalid value shows a sidebar error, and no analysis runs.
- **Analyses:**
  - Run only for a usable dataset, through `cluster_dataset`, `estimate_density` and `summarize_results`.
  - Cached in `st.session_state["analysis_cache"]`. The cache is reused only when it holds the **same dataset object** and the same parameter key (`analysis_cache_key`, covering every config field); otherwise it is recomputed.
  - Each analysis can fail on its own, and its `AnalysisError` text is shown. The KDE grid-cap error is shown as-is, never silently coarsened.
- **Pages:**
  - **Clusters:** cluster map, metrics, summary table, and a Plotly cluster-size chart (all members and members shown under filters; candidates outlined).
  - **Density:** density map, legend and threshold explanation, and a table of the parameters used.
  - **Summary:** the `SpatialSummary` values, with `None` shown as "Not run". Also the method-comparison 2×2 table and per-cluster table, the notes, and Plotly charts by severity and incident type (from `by_category`) and by date (`incidents_by_period`). Charts appear only when their columns exist.
  - **Data:** unchanged.
  - **History & Reports:** a placeholder at Stage 7. It now lists saved runs (Stage 8) and offers report downloads (Stage 9); see those sections.
- **Display-only filters** (Clusters page sidebar): severity and incident type (missing values appear as "(missing)"), "Show noise points", and "Candidate hotspots only".
  - `dashboard.display_mask` builds a positional boolean mask that only selects what the cluster map and the "shown" bars draw.
  - DBSCAN labels, KDE values, the summary and the comparison denominators always use **all** accepted incidents. Tests check that the cached result objects are unchanged after filtering.
  - The density map and the Summary page say that the filters don't apply to them.

### `incidents_by_period(dataset)`
- **Input:** the Stage 2 date contract (ISO 8601 → datetime64, NaT for blank or unparseable).
- **Missing dates:** NaT rows are counted in `missing_dates` and never imputed.
- **Time zones:** time-zone-aware values, including mixed offsets that the validator leaves as an object column, are converted to UTC; naive values are used as-is.
- **Period:** chosen from the span between the earliest and latest dates: ≤ 62 days → `"day"`, ≤ 1096 days → `"month"`, otherwise `"year"`. Every period between the first and the last is listed, with 0 where there are no incidents.
- **Returns** `{"column_present", "period", "counts": DataFrame[period_start, incident_count], "dated_incidents", "missing_dates"}`.

## Stage 8 decisions (orchestration and history)
- **`run_analysis`:** `load_and_validate` (with `config.study_area`) → if usable: `cluster_dataset`, `estimate_density`, `summarize_results` → `AnalysisRun` (`run_id` = `uuid4().hex`, `created_at` = UTC now) → `save_run` when `persist=True`.
  - **An unusable dataset** stops before DBSCAN and KDE; the run has `None` results and is still saved.
  - **Analysis or load errors propagate**, and **failed runs are never saved** (decision A).
  - **`persist=False`** never opens or creates the database.
  - **`db_path`** is a keyword-only argument (decision D), so tests and checks use temporary databases.
- **`record_run`** (decision D) saves results that were already computed, for the dashboard's Save button. It shares the run-building code with `run_analysis`.
- **What `record_run` enforces.** Every check runs **before** anything is written, and any failure raises `AnalysisError`, so a rejected call never creates or changes the database.
  1. **Complete run:** for a usable dataset, the clusters, density and summary must all be present.
  2. **Same dataset:** `summary == summarize_results(dataset, clusters, density)`. This includes the Stage 6 check that index, IDs and coordinates match.
  3. **Configuration matches the results.** Every mismatch found is reported in one message.
     - **DBSCAN:** `clusters.params` `eps_m` and `min_samples` equal `config.dbscan`.
     - **KDE:** `density.params` `bandwidth_m`, `kernel`, `grid_cell_m` and `high_density_quantile` equal `config.kde`.
     - **Study area, if none is configured:** the KDE grid must come from the data extent (`grid_source == "data_extent_padded"`).
     - **Study area, if one is configured:** the grid source must be `"study_area"` and `grid_extent` must equal the box. Also, no accepted incident may lie outside the box, which the validator guarantees for a dataset validated with that box.
     - **Candidate hotspots:** every cluster's `is_candidate_hotspot` must equal `incident_count >= config.hotspot.min_incidents`.
  4. **Unusable dataset:** all three results must be `None`.
- **What `record_run` cannot check:**
  - **`random_seed` and `min_density_per_km2`** affect no result in the current algorithms, so any value is accepted.
  - **`min_incidents`** is visible only through the candidate flags; `ClusterResult` records no criteria. Values that give identical flags can't be told apart (e.g. 7 and 8 for clusters of 12 and 6). Both describe the same results.
  - **An unusable dataset** has no results to compare. The configuration is stored as given, and whether the dataset was validated with that `study_area` can't be verified.
  - **Fixed algorithm constants** such as the 3-bandwidth padding aren't part of `AnalysisConfig` and aren't saved. See development plan Open item 4.
- **`database`:**
  - **`init_db`** creates the folder and table; it is safe to call repeatedly.
  - **`save_run`** stores `created_at` as UTC ISO-8601 with microseconds, so text order equals time order; naive datetimes are rejected.
    - The cluster columns are NULL when DBSCAN didn't run.
    - `report_paths_json` starts NULL; Stage 9's `set_report_paths` fills it once.
    - A duplicate `run_id` raises `IntegrityError`, and the failed insert is rolled back.
  - **`list_runs`** returns runs newest first (`created_at`, then `run_id`), with a validated `limit`.
    - It opens the database **read-only** and **never creates it**; a missing file returns `[]`.
    - It decodes `config_json` into `config` (an `AnalysisConfig`) and `report_paths_json` into `report_paths`.
    - A file without the history table raises `OperationalError`.
  - **Connections** commit on success, roll back on error, and are always closed.
- **Configuration round trip:**
  - `config_json = {"schema_version": 1, "config": asdict(config)}`, written with `allow_nan=False`.
  - `config_from_json(config_to_json(c)) == c` exactly, floats bit for bit. NaN is refused before anything is written.
- **Dashboard:**
  - **Summary page:**
    - A **"Save this run to history"** button (decision C) appears only when DBSCAN, KDE and the summary all completed.
    - **Saved-once guard:** the saved `run_id` is kept on the analysis cache entry, which belongs to exactly one dataset object plus one parameter set. So the same analysis can't be saved twice, while a new parameter set or dataset can be saved once too.
    - **Errors on save** are shown as "Could not save the run: …", and the run is not marked as saved.
  - **History & Reports page:**
    - Lists up to 50 runs, newest first, with the stored parameters; NULL results are shown as "Not run" or "unusable dataset".
    - **Errors on read** are shown as "Could not read the run history: …".
    - A notice says reports arrive in Stage 9.
  - **History location:** the page and button use the module setting `HISTORY_DB_PATH`, which defaults to `config.settings.DB_PATH` and can be redirected with `HOTSPOT_DB_PATH`.

## Stage 9 decisions (CSV and PDF reports)
- **Eligibility (A):** reports are generated only for a **saved, complete, usable** run held in the current session.
  - The run must have clusters, density and summary (with the method comparison).
  - A history row with its `run_id` must exist, and its config, source name and row counts must match the run.
  - No report paths may be registered yet.
  - The history stores parameters, not results, so runs from earlier sessions **cannot** be regenerated. Their reports can only be downloaded if they were registered and the files still exist.
- **Layout and no overwriting (C):**
  - Files go to `REPORTS_DIR/<run_id>/incidents.csv`, `clusters.csv` and `report.pdf`.
  - Every file is created exclusively (`x` mode); an existing file raises `FileExistsError`.
  - An existing `<run_id>` folder is refused. Reports are generated once per run.
- **`generate_reports` workflow (B):**
  1. Check eligibility.
  2. Refuse an existing run folder.
  3. Write the files into a new temporary folder inside the reports root.
  4. Check them: non-empty CSVs with a UTF-8 BOM, and a PDF with `%PDF-` … `%%EOF`.
  5. Rename the temporary folder to `<run_id>` (no overwrite).
  6. Register the paths.

  **This is not a true transaction across disk and database.** On any failure:
  - the folders created by the attempt are removed (the temporary folder, or the renamed run folder if the database step failed);
  - the reports root is removed too, if this attempt created it and it is now empty;
  - the database is unchanged, and the error propagates.

  Nothing that existed before the attempt is deleted, and the run object is not changed.
- **Stored paths (D):**
  - Paths are stored **relative to the reports root** as POSIX strings (`"<run_id>/report.pdf"`), still as a JSON list, so `list_runs` keeps its return type.
  - `set_report_paths` refuses paths outside the root. It updates only with one parameterized `UPDATE … WHERE run_id = ? AND report_paths_json IS NULL`, and raises `LookupError` for an unknown run or `ValueError` if paths are already set.
  - `resolve_report_path` refuses absolute paths, `..`, and anything that resolves outside the root.
  - **Limitation:** if `HOTSPOT_REPORTS_DIR` changes, stored paths resolve against the new folder and the files will show as missing.
- **`incidents.csv`:**
  - One row per accepted incident, in file order: `source_row` (the cleaned frame's index), then every column of the clustered frame in order (required, optional and extra columns unchanged, then `cluster_label`), then `is_noise` and `cluster_is_candidate_hotspot`.
  - A data column that already uses one of these three names is refused.
  - **No per-incident KDE flag (H).**
- **`clusters.csv`:** every cluster in label order: `cluster_label`, `incident_count`, `centroid_lat`, `centroid_lon`, `radius_m`, `is_candidate_hotspot`, `eligible_members`, `outside_grid_members`, `members_at_high_density`, `high_density_share`.
- **CSV format (E):**
  - Python `csv` writer, minimal quoting, CRLF line endings, **UTF-8 with BOM**.
  - Floats are written with `repr` so they round-trip exactly. Booleans are `true`/`false`, dates are ISO 8601, and missing values are empty cells.
  - **Text is written exactly as stored.** Nothing is prefixed or rewritten, so formula-like cells such as `=1+1` stay as they are.
  - The dashboard and the PDF show `CSV_SAFETY_WARNING` about spreadsheet formula execution.
- **PDF:**
  - ReportLab, A4, built in **invariant mode** so the same run gives identical bytes.
  - Content comes from `report_sections(run)`, in this order: Run; Data quality; Parameters (every `AnalysisConfig` field); DBSCAN clusters; KDE density; DBSCAN vs KDE; Incidents by category; Limitations and notes.
  - **Cluster cap (F):** at most 50 clusters in ascending label order, always stating that `clusters.csv` contains all clusters.
  - The limitations cover descriptive-only results, the candidate size rule, relative density, the CSV warning, the summary and comparison notes, and all four open items.
  - **Text safety:** every value is mapped to Helvetica's Windows-1252 characters (`≥` becomes `>=`; anything else unsupported becomes a visible `[U+XXXX]`) and XML-escaped before it reaches ReportLab markup.
  - **No maps** in the PDF.
- **Dashboard:**
  - **Summary page:** after "Save", a **Generate reports** button offered once per saved run (kept on the cache entry), then three download buttons. Errors show as "Could not generate reports: …", and a retry is possible.
  - **History & Reports page:** the history table gains a `reports` column. Choosing a run shows downloads for files that exist, and files missing from disk are flagged as missing.
  - Both pages show the CSV safety warning.
  - Tests patch `HISTORY_REPORTS_DIR`. The app itself uses `REPORTS_DIR`, which can be redirected with `HOTSPOT_REPORTS_DIR`.

## Stage 10B Phase 1 (design system)
- **`.streamlit/config.toml`** applies the approved palette, typography (Inter; body 15 px; h1/h2 28 px, h3 20 px, h4 16 px at weight 600; metric values 28 px), widget borders, a 6 px radius, the navy sidebar, status colours and native chart colours. It uses Streamlit's native theme only, with no custom CSS.
- **`modules/ui_theme.py`** holds the same values as constants, plus `plotly_template()`. This is a Plotly template that is not registered globally; pages opt in later. The module does **not** import Streamlit. It only references the analytical palettes from `map_visualization`, so cluster, noise, density and threshold colours are unchanged.
- **Font fallback:** Streamlit 1.66 keeps only the first font family, so the effective UI stack is Inter → Streamlit's bundled Source Sans → sans-serif. Plotly charts use the full `FONT_STACK`.
- **Unchanged:** page code, widget labels and keys, and behaviour. `tests/test_ui_theme.py` checks the tokens, that the TOML agrees with the module, WCAG contrast, the template, and the palettes.

## Stage 10B Phase 2 (application shell)
- **Navigation (`app.py`):**
  - `st.navigation(position="hidden")` with one `st.Page` per page, each calling `render_page(name)`.
  - The sidebar shows the brand ("Hotspot Analytics" / "Spatial Incident Analysis"), then `st.page_link` items with Material icons.
  - The current page's link is wrapped in `st.container(key=NAV_ACTIVE_KEY)`, and `ui_theme.SHELL_CSS` (static, built from tokens) gives it the teal accent with white text. Phase 4.2 adds static KPI-card rules to the same constant.
  - The default page (Data) is served at `/`. Streamlit doesn't route `/data`; opening it shows "Page not found" and falls back to Data.
- **`render_page(name)`** is unchanged as the entry point. It now:
  - creates a sidebar status container first and fills it after the page runs;
  - shows the file name (Markdown-escaped with `escape_markdown`), rows / accepted / rejected, the analysis status (`analysis_status`: Not run · Complete · Partial — DBSCAN/KDE/summary failed · Failed · Dataset unusable), and the saved run ID (first 8 characters).
- **Page headers:** `_page_header` keeps the existing title text and adds a one-line description (`PAGE_INFO`).
- **KPI strip:** `kpi_strip` (≤ 4 bordered `st.metric` cards per row, via `kpi_rows`) shows only values that already exist, and `NOT_RUN` when an analysis didn't produce a value. Existing labels and values are unchanged:
  - **Data:** Rows in file, Accepted, Rejected.
  - **Clusters:** Clusters, Candidate hotspots, Noise incidents, Analysis status.
  - **Density:** Incidents used, Grid cells, Bandwidth, Analysis status.
  - **Summary:** Rows in file, Accepted incidents, Rejected, Analysis status, Clusters, Candidate hotspots, Noise incidents, Noise share.
  - **History:** Saved runs, Runs with reports.
- **Sidebar:** analysis parameters are in a collapsed "Analysis parameters" expander. Display filters are in a separate expander on the Clusters page only (renamed in Phase 3). Widget keys are unchanged.
- **Loading:** `st.spinner` messages wrap DBSCAN, KDE and the summary. With the small sample these finish in well under a second, so the spinner is rarely visible.
- **Empty states:** same texts and message types, with Material icons added.

## Stage 10B Phase 3 (analysis pages)
Layout and wording only. DBSCAN, KDE, the summary, validation, parameters, map colours, reports and widget keys are unchanged.
- **Data:** a bordered "Data source" card (upload instructions, the radio, the uploader or sample selector). Below it, "Validation summary" shows the escaped file name and the KPIs Rows in file, Accepted, Rejected and Validation status (`validation_status`: Ready · Ready with rejections · Unusable). One success, warning or error message says whether the dataset is ready for analysis. Then the tabs "Incident Map", "Validation Issues (n)" and "Data Preview".
- **Clusters:** the KPIs are Clusters, Candidate hotspots, Noise incidents and Noise share. Noise share comes from `summary.noise_share`; all four show `NOT_RUN` when DBSCAN failed. The analysis status stays in the sidebar status block. The map and an explanation panel sit side by side (`MAP_PANEL_RATIO` 2 : 1; stacked on narrow screens). The panel covers the legend and the min_incidents size rule from this run's configuration, and makes no significance claim. The cluster summaries are in "Table" and "Cluster sizes" tabs; the chart uses `ui_theme.plotly_template()` with its existing bar colours. The filter expander is labelled `FILTERS_LABEL` ("Display filters — visualization only; analysis results remain unchanged."), and filter behaviour is unchanged.
- **Density:** the map and an info panel sit side by side. The panel holds `KDE_DISCLAIMER` and short notes on KDE, bandwidth, grid cell, relative scores and the threshold layer. The colour-scale notes are kept. "Parameters used" shows a one-line summary, with the full table in an "All KDE parameters" expander.

## Stage 10B responsive fix (charts and map controls)
Rendering only; layers, layer names, colours and data are unchanged.
- Cluster and density maps: the layer control starts collapsed in the top-right (`LAYER_CONTROL_POSITION`) and expands on hover or tap; zoom is bottom-left (`ZOOM_CONTROL_POSITION`). The incident map has a single layer and no layer control.
- `DENSITY_LEGEND_WIDTH_PX` is 480 (the caption still fits) so the legend fits the two-thirds map at 1280 px. On narrower maps (phone width), `_ResponsiveLegend` re-fits the legend's own D3 scale to the map width, keeping the colours, the 0–1 domain, the ticks and the font size. If the caption doesn't fit, it wraps onto two lines at the dash. It runs again when the map is resized; wider maps keep the 480 px legend unchanged (Phase 3.2).
- Cluster-size chart: a two-line title, the legend below the plot and automargins, so nothing is cut off or overlapping at 390 px.

## Stage 10B Phase 4.2 (design system and KPI cards)
Display only. KPI labels and values, widget keys and sidebar labels are unchanged.
- **Tokens (`ui_theme`):** `SHADOW_CARD`, `RADIUS_CARD_PX` (10), `SPACING_PX` (4, 8, 12, 16, 24, 32) with `SPACE_XS` to `SPACE_2XL`, `KPI_LABEL_PX`, `KPI_LABEL_WEIGHT`, and `BADGE_BACKGROUND` / `BADGE_TEXT` per tone. Backgrounds are 12% tints of the status colours; text is the status colour darkened to 70%, at least 4.5:1 on the tint.
- **KPI cards:** `kpi_strip` still renders `st.metric`, each inside a keyed container (`kpi_key`). `SHELL_CSS` styles keys starting `kpi_` as white cards. Inside them it uses the metric's `data-testid` label and value hooks, because `st.metric` offers no other way to size the label or colour the value.
- **Status badges:** `kpi_tone` maps Analysis status and Validation status to success, warning, error or info. The status text is always shown, so colour is never the only signal. Long badge text wraps onto two lines inside the card, within the 104 px height, and card content is top-aligned so labels line up across a row.
- **Config:** `client.toolbarMode = "minimal"` hides the developer toolbar. `theme.paddingTop = "2rem"` reduces the main-area gap, and `theme.sidebar.paddingTop = "1rem"` stops the sidebar inheriting it, keeping the sidebar in its original position.

## Stage 10B Phase 4.3 (Summary page)
Layout and wording only. Analysis values, widget keys, report generation and the other pages are unchanged.
- **Always visible:** the scope caption, then an "Overview" with the KPIs, the bounding box and mean centre, and a white panel holding "Save to history" and "Reports". `save_run` and `generate_reports` are now primary buttons.
- **Tabs (`SUMMARY_TABS`):** Method Comparison (both tables and the eligibility caption), Distributions (severity and type charts side by side, stacked on phones, then the date chart) and Notes & Limitations.
- **Synthetic notice:** `SYNTHETIC_NOTICE` appears when `is_synthetic_source` finds "synthetic" in the file name, which `data/sample/README.md` requires for synthetic files.
- **KPIs:** `kpi_grid` is `kpi_strip`'s wrapping form: four across on desktop, two on phones. It is used on this page only.
- **Charts:** `_summary_bar_chart` uses `ui_theme.bar_chart_layout` (shared template, two-line title, no legend) with the accent colour and value labels. It replaces the hard-coded bar colour. Bars keep the same data.
- **Panels:** containers keyed `summary_panel_*` are styled by `SHELL_CSS`.

## Stage 10B Phase 4.4 (tables, empty states, History)
Display only. Stored runs, report files, sorting, widget keys and the data behind each table are unchanged.
- **Tables:** headings are Title Case through `column_config`, or `column_label` for data columns. The underlying frames keep their original column names. `TABLE_SCROLL_HINT` appears under tables that can be wider than a phone.
- **Data Preview:** the index stays visible as "Source Row", because it is the 0-based row number used by Validation Issues and by `source_row` in `incidents.csv`. Date columns show the date alone unless a value has a time.
- **Empty states:** `empty_state` puts a heading, the existing message (same text prefix and message type) and an optional next step in a white card. Links use `st.page_link` with the `st.Page` objects that `app.py` stores under `PAGE_LINKS_KEY`; when a page runs alone, the link is skipped.
- **History:** one frame feeds two views through `column_order`: results (`HISTORY_RESULT_COLUMNS`), and run ID with parameters in an expander (`HISTORY_PARAMETER_COLUMNS`). `CSV_SAFETY_WARNING` shows only when a run has reports. The run selector shows the saved time, file and short ID, and still returns the full run ID.

## Invariants every implementer must keep
- Input frames are never mutated. Return new frames.
- `labeled_frame` keeps every clean row, in the same order, with `cluster_label` added.
- Every unit is stated: metres for distances, degrees for stored coordinates, radians only inside the sklearn calls.
- `params` dicts in results record exactly what was passed to sklearn, so a run can be reproduced.

## Working independently
Each owner codes against hand-built contract objects, for example a `CleanDataset` built from the synthetic fixture in `tests/conftest.py`. Nobody waits on upstream code. Integration (Stage 8) then only has to wire up functions that are already tested.
