# Project Requirements

**Status: Stages 1–9 implemented and tested** (see `development_plan.md`). FR1–FR9 below are implemented, with two partial points:
- **FR1:** the sample list contains only a clearly labelled synthetic file (`data/sample/synthetic_demo.csv`). No real-world dataset has been selected.
- **FR3:** the study-area box is applied by validation, KDE and the controller, but it is set in `config/settings.py`; the dashboard has no control for it.

The requirements are unchanged from the original plan.

## Problem statement
Incident records with geographic coordinates (initially road accidents) are usually reviewed as tables, which hides where incidents concentrate. Planners need a repeatable way to load such data, check its quality, find spatial clusters and high-density areas, and share the findings, without overstating what the methods prove.

## Objectives
1. Load a point-incident dataset and validate it against a documented schema.
2. Find density-connected clusters with geodesic DBSCAN.
3. Estimate a continuous density surface with KDE.
4. Present points, clusters and density on interactive maps with charts and filters.
5. Keep a history of analysis runs and their parameters (SQLite).
6. Export results as CSV and a PDF summary that states the method's limitations.

## Intended users
Students and evaluators; urban/traffic planners and analysts who have CSV incident data; anyone repeating the workflow on another point-incident domain.

## Functional requirements
| ID | Requirement |
|---|---|
| FR1 | Upload a CSV, or pick a file from `data/sample/`. |
| FR2 | Validate required columns, coordinate types and ranges, and duplicate IDs; reject invalid rows and report them. Never impute. |
| FR3 | Optionally restrict analysis to a configured study-area bounding box, and report any points outside it. |
| FR4 | Run DBSCAN with haversine distance; `eps` set in metres; label noise. |
| FR5 | Summarise clusters (count, centroid, radius) and flag *candidate* hotspots using documented criteria. |
| FR6 | Run KDE with haversine distance; bandwidth set in metres; evaluate on a grid; mark the high-density quantile. |
| FR7 | Show interactive maps for points, clusters and density, plus charts by severity, type and date when those columns exist. |
| FR8 | Save each run's metadata and parameters; list past runs. |
| FR9 | Export CSV (labelled incidents, cluster table) and a PDF summary. |

## Non-functional requirements
- Reproducible: every result-affecting parameter is stored with its run, and the random seed is fixed.
- Analytical modules are independent of Streamlit and covered by pytest.
- No absolute paths, embedded secrets, silent error suppression or fabricated data.
- Handles up to about 500k rows (`MAX_UPLOAD_ROWS`). Performance at that size is **unverified**.

## Initial scope
A single-user local Streamlit app working on CSV point data in WGS 84.

## Explicitly excluded
Authentication, cloud deployment, a separate backend or React frontend, live tracking, predictive ML, and routing or network analysis. Formal significance testing (e.g. Getis-Ord Gi*) is a possible later extension, not in scope yet.

## Assumptions and limitations
- No verified Ahmedabad dataset is available yet. Choosing one is a Stage 2 task.
- Input coordinates are assumed to be WGS 84 decimal degrees. Other CRSs are out of scope unless converted beforehand.
- Results depend on data completeness and on reporting bias in the source data.
- DBSCAN clusters and KDE peaks are descriptive. They do **not** establish statistical significance.
