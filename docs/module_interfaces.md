# Module Interfaces

The signatures exist in code now. Bodies raise `NotImplementedError("Stage N: ...")`. Types come from `modules/contracts.py` and `config/settings.py`. Changing a signature needs team agreement and an update to this file in the same commit.

| Function | Input | Output | Errors | Stage |
|---|---|---|---|---|
| `data_manager.list_sample_datasets(directory)` | `Path` | `list[Path]` | — | 1 (done) |
| `data_manager.load_raw_dataset(source, source_name=None)` | `Path \| BinaryIO` | `(DataFrame, str)` | `DataValidationError` | 2 |
| `data_validator.validate_and_clean(raw, source_name, study_area=None)` | `DataFrame, str, StudyArea?` | `CleanDataset` (may be empty: `report.is_usable == False`) | `DataValidationError` **only** for a missing required column | 2 |
| `data_validator.summarize_quality(report)` | `ValidationReport` | `DataFrame` | — | 2 |
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

## Invariants every implementer must keep
- Input frames are never mutated. Return new frames.
- `labeled_frame` keeps every clean row, in the same order, with `cluster_label` added.
- Every unit is stated: metres for distances, degrees for stored coordinates, radians only inside the sklearn calls.
- `params` dicts in results record exactly what was passed to sklearn, so a run can be reproduced.

## Working independently
Each owner codes against hand-built contract objects, for example a `CleanDataset` built from the synthetic fixture in `tests/conftest.py`. Nobody waits on upstream code. Integration (Stage 8) then only has to wire up functions that are already tested.
