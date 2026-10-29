# Dataset Specification

**Supported input:** UTF-8 CSV with a header row, `.csv` extension in any case. A UTF-8 byte-order mark is accepted. Maximum 500,000 rows (configurable). Other formats are not supported yet.

## File-level rules (`load_raw_dataset`, implemented in Stage 2)
These raise `DataValidationError`, and nothing is analysed:
- the file is missing, is not a regular file, or can't be read;
- the extension isn't `.csv`, or the file isn't UTF-8;
- the file is empty or whitespace-only (no header);
- a header name is duplicated;
- any data row has a different number of fields than the header (the error lists the file line numbers);
- a quoted field is unterminated;
- the file has more than the row limit. It is refused, not truncated.

Every cell is read as **text exactly as written**. There is no NA-guessing: `NA`, `null` and blanks stay as text. Whitespace is kept, and column names are never renamed or trimmed. All interpretation happens in the validator.

Completely blank lines are not records and are skipped. Row index `i` is the i-th data record, 0-based. It equals file line `i + 2` when the file has no blank lines and no multi-line quoted fields. A file with a header and no data rows loads fine and is then reported as unusable.

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
6. The first occurrence holds its ID **even if that row is later rejected for its coordinates**. Later rows with the same ID stay `DUPLICATE_ID` and are not promoted to replace it. Choosing which duplicate is "right" would be a guess.

## One code per rejected row
Rules are evaluated in this order, and a rejected row is reported under the **first** rule it fails only:
1. `MISSING_ID`
2. `DUPLICATE_ID`
3. `MISSING_COORDINATE`
4. `NON_NUMERIC_COORDINATE`
5. `NON_FINITE_COORDINATE`
6. `LAT_OUT_OF_RANGE`
7. `LON_OUT_OF_RANGE`
8. `OUTSIDE_STUDY_AREA`

Within the three coordinate-type checks (3–5), a problem in either latitude or longitude triggers the code. The range checks test latitude before longitude. So every error row appears in exactly one issue, and `rejected_rows` equals the number of distinct rejected rows.

The cleaned frame keeps the **source row index** (it is not renumbered) and the input order. Accepted rows can therefore be traced back to the file.

## Optional columns
| Column | Type | Rule when present | When absent |
|---|---|---|---|
| `incident_date` | datetime64 | Only ISO 8601 is parsed (`2024-03-05`, `2024-03-05T14:30`). Other formats, including `05/03/2024`, become NaT and are reported as `UNPARSEABLE_DATE`, because day-first vs month-first can't be decided safely. A blank date is NaT with no warning. | Time charts and filters are hidden |
| `incident_type` | category (string) | Whitespace trimmed; case kept; blank → null | Type breakdown hidden |
| `location_name` | string | Kept exactly as given | Not used |
| `severity` | category (string) | Trimmed; blank → null. There is no fixed list of allowed values yet; that waits until a real dataset is chosen. | Severity breakdown hidden |

Any other columns are kept unchanged and listed in the validation report.

## Coordinate rules
- Values must be decimal degrees. DMS strings such as `23°01'N` are rejected, not parsed.
- Surrounding whitespace is trimmed before parsing. A decimal comma (`23,0`), a suffix (`23.0N`) or the text `NaN` is non-numeric.
- `inf`, `-Infinity` and similar values are non-finite.
- The legal bounds (±90, ±180) are inclusive.
- Rows with a null, non-numeric, non-finite or out-of-range coordinate are **rejected** (excluded from analysis) and listed in the report with an issue code (`MISSING_COORDINATE`, `NON_NUMERIC_COORDINATE`, `NON_FINITE_COORDINATE`, `LAT_OUT_OF_RANGE`, `LON_OUT_OF_RANGE`).
- `(0, 0)` is flagged as `NULL_ISLAND` (a warning) because it almost always means a missing value.
- Swapped lat/lon (for example lat ≈ 72, lon ≈ 23 for Ahmedabad) is detectable only against a study area. Points outside the box are flagged `OUTSIDE_STUDY_AREA` and excluded when a study area is set.

## Issue codes
| Code | Severity | Effect |
|---|---|---|
| `MISSING_ID` | error | Row rejected |
| `DUPLICATE_ID` | error | Row rejected (first occurrence kept) |
| `MISSING_COORDINATE`, `NON_NUMERIC_COORDINATE`, `NON_FINITE_COORDINATE`, `LAT_OUT_OF_RANGE`, `LON_OUT_OF_RANGE` | error | Row rejected |
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
