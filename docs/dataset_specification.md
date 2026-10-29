# Dataset Specification

**Supported input:** UTF-8 CSV with a header row. Maximum 500,000 rows (configurable). Other formats are not supported yet.

## Required columns
| Column | Type after cleaning | Rule |
|---|---|---|
| `incident_id` | string | Non-empty after trimming whitespace. See *Incident ID rules* below. |
| `latitude` | float64, decimal degrees WGS 84 | Numeric, not null, −90 ≤ lat ≤ 90 |
| `longitude` | float64, decimal degrees WGS 84 | Numeric, not null, −180 ≤ lon ≤ 180 |

If any required **column** is missing, the whole dataset is refused with `DataValidationError`.

If the columns are present but **no row** survives validation, no exception is raised. `validate_and_clean` returns a `CleanDataset` with an empty frame and `report.is_usable == False`. The controller must check `is_usable` and must not run DBSCAN, KDE or summaries on an unusable dataset.

## Incident ID rules
This is the only duplicate-handling rule in the project. No other module may drop or merge rows by ID.
1. IDs are compared as strings after trimming leading and trailing whitespace. Comparison is case-sensitive.
2. A null, empty or whitespace-only ID makes the row **rejected** with error `MISSING_ID`. Such rows are not considered in duplicate checks.
3. The **first** occurrence of each non-empty ID, in file order, is kept. Every later occurrence is **rejected** with error `DUPLICATE_ID`.
4. Each `DUPLICATE_ID` issue lists the rejected rows' original indices in `row_indices`. Its `message` names the duplicated ID and the index of the kept row, so every rejection can be traced. Nothing is removed silently.
5. ID checks run before the coordinate checks. A row rejected for its ID is counted once, under its ID issue.

## Optional columns
| Column | Type | Rule when present | When absent |
|---|---|---|---|
| `incident_date` | datetime64 | Parsed. Unparseable values become NaT and are reported as a warning. | Time charts and filters are hidden |
| `incident_type` | category (string) | Whitespace trimmed; case kept | Type breakdown hidden |
| `location_name` | string | Kept as given | Not used |
| `severity` | category (string) | Trimmed. The set of allowed values is decided by the dataset in Stage 2. | Severity breakdown hidden |

Any other columns are kept unchanged and listed in the validation report.

## Coordinate rules
- Values must be decimal degrees. DMS strings such as `23°01'N` are rejected, not parsed.
- Rows with a null, non-numeric or out-of-range coordinate are **rejected** (excluded from analysis) and listed in the report with an issue code (`MISSING_COORDINATE`, `NON_NUMERIC_COORDINATE`, `LAT_OUT_OF_RANGE`, `LON_OUT_OF_RANGE`).
- `(0, 0)` is flagged as `NULL_ISLAND` (a warning) because it almost always means a missing value.
- Swapped lat/lon (for example lat ≈ 72, lon ≈ 23 for Ahmedabad) is detectable only against a study area. Points outside the box are flagged `OUTSIDE_STUDY_AREA` and excluded when a study area is set.

## Issue codes
| Code | Severity | Effect |
|---|---|---|
| `MISSING_ID` | error | Row rejected |
| `DUPLICATE_ID` | error | Row rejected (first occurrence kept) |
| `MISSING_COORDINATE`, `NON_NUMERIC_COORDINATE`, `LAT_OUT_OF_RANGE`, `LON_OUT_OF_RANGE` | error | Row rejected |
| `OUTSIDE_STUDY_AREA` | error (only when a study area is set) | Row rejected |
| `NULL_ISLAND` | warning | Row kept, flagged |
| `UNPARSEABLE_DATE` | warning | Row kept, date set to NaT |

`error` means the row is excluded from analysis. `warning` means the row is kept. `ValidationReport.valid_rows + rejected_rows == total_rows` always holds.

## Missing-data policy
Nothing is imputed or invented. A missing ID or coordinate excludes the row. Missing optional values stay null. Every exclusion is counted and listed in the report.

## Representations used downstream
See `modules/contracts.py`:
- `CleanDataset` is the cleaned frame plus its validation report.
- `ClusterResult` adds `cluster_label` (−1 = noise).
- `DensityResult` is the grid axes, the density array and the threshold.
- `SpatialSummary` holds descriptive statistics.
- `AnalysisRun` bundles all of these with its config for history and reports.
