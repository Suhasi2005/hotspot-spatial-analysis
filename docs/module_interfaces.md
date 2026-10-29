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
| `dbscan_analysis.run_dbscan(dataset, params, criteria)` | `CleanDataset, DBSCANParams, CandidateHotspotCriteria` | `ClusterResult` | `AnalysisError` | 4 |
| `density_analysis.run_kde(dataset, params, study_area=None)` | `CleanDataset, KDEParams, StudyArea?` | `DensityResult` | `AnalysisError` | 5 |
| `spatial_statistics.haversine_m(lat1, lon1, lat2, lon2)` | degrees | metres | — | 4 (written by M2) |
| `spatial_statistics.summarize(dataset, clusters, density)` | either result may be `None` | `SpatialSummary` | — | 6 |
| `map_visualization.build_incident_map(dataset)` | `CleanDataset` | `folium.Map` | — | 3 |
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

## Invariants every implementer must keep
- Input frames are never mutated. Return new frames.
- `labeled_frame` keeps every clean row, in the same order, with `cluster_label` added.
- Every unit is stated: metres for distances, degrees for stored coordinates, radians only inside the sklearn calls.
- `params` dicts in results record exactly what was passed to sklearn, so a run can be reproduced.

## Working independently
Each owner codes against hand-built contract objects, for example a `CleanDataset` built from the synthetic fixture in `tests/conftest.py`. Nobody waits on upstream code. Integration (Stage 8) then only has to wire up functions that are already tested.
