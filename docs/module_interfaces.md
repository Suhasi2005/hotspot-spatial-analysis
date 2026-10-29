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
| `density_analysis.run_kde(dataset, params, study_area=None)` | `CleanDataset, KDEParams, StudyArea?` | `DensityResult` | `AnalysisError` | 5 |
| `spatial_statistics.haversine_m(lat1, lon1, lat2, lon2)` | degrees (scalars) | metres | — | 4 (done, written by M2) |
| `spatial_statistics.summarize(dataset, clusters, density)` | either result may be `None` | `SpatialSummary` | — | 6 |
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

## Invariants every implementer must keep
- Input frames are never mutated. Return new frames.
- `labeled_frame` keeps every clean row, in the same order, with `cluster_label` added.
- Every unit is stated: metres for distances, degrees for stored coordinates, radians only inside the sklearn calls.
- `params` dicts in results record exactly what was passed to sklearn, so a run can be reproduced.

## Working independently
Each owner codes against hand-built contract objects, for example a `CleanDataset` built from the synthetic fixture in `tests/conftest.py`. Nobody waits on upstream code. Integration (Stage 8) then only has to wire up functions that are already tested.
