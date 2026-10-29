# Hotspot Identification and Spatial Analysis

A Streamlit GIS application that validates point-incident data, finds spatial clusters (geodesic DBSCAN), estimates density (haversine KDE), and reports the results. The first demonstration domain is road accidents, but the design works for any point-incident data.

**Status: Stages 1–9 implemented and tested** (see [docs/development_plan.md](docs/development_plan.md)). The application provides:
- CSV upload and validation, with a data-quality report;
- DBSCAN clustering;
- KDE density estimation;
- spatial statistics and a DBSCAN vs KDE comparison;
- incident, cluster and density maps;
- an interactive dashboard with Plotly charts and display filters;
- a saved analysis history;
- CSV and PDF report exports.

Stage 10 (evaluation and demonstration) has not started.

All results are **descriptive**. DBSCAN clusters, KDE high-density areas and "candidate hotspots" are **not** statistically significant hotspots; no significance test is run.

## Setup (Windows PowerShell)
```powershell
python --version                # must report 3.12.x
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
```
macOS/Linux: `python3.12 -m venv .venv && source .venv/bin/activate`, then the same `pip` commands.

## Run (with the venv activated)
```powershell
python -m streamlit run app.py
python -m pytest -q -rs
python scripts/check_structure.py
```
Use `python -m ...` so the commands use the venv's packages. The system Python on a shared machine may not have them. **The maps need internet access** to load the OpenStreetMap tiles; everything else runs locally.

## Using the application
1. **Data page:** upload a CSV, or pick `synthetic_demo.csv` from the sample list.
   - **Required columns:** `incident_id`, `latitude`, `longitude` (WGS 84 decimal degrees).
   - **Optional columns:** `incident_date` (ISO 8601, e.g. `2024-03-05`), `incident_type`, `severity`, `location_name`. Any other columns are kept unchanged.
   - Invalid rows are rejected and listed with a reason. Nothing is imputed.
   - The **incident map** shows the accepted points. Full rules: [docs/dataset_specification.md](docs/dataset_specification.md).
2. **Clusters (DBSCAN) page:** the **cluster map** colours each cluster and draws its extent (centroid + radius).
   - **Noise** (grey) is an incident that belongs to no cluster under the current `eps_m` and `min_samples`.
   - A **candidate hotspot** (thick black outline) is a cluster with at least `min_incidents` incidents. That is a size rule only.
3. **Density (KDE) page:** the **density map** draws the KDE grid.
   - The values are **relative density scores** (a probability density over the earth's surface, scaled to the grid's maximum for colour). They are **not** incident counts and **not** incidents/km².
   - An optional layer marks cells at or above the run's quantile threshold.
4. **Summary page:** summary statistics, the descriptive DBSCAN vs KDE comparison table, and charts by severity, type and date (shown only when those columns exist).
5. **Sidebar:** the analysis parameters re-run DBSCAN and KDE on all accepted incidents. The **display filters** on the Clusters page (severity, type, show noise, candidates only) change only what is drawn; they never change the analysis.
6. **Save, history and reports:**
   - On the Summary page, **Save this run to history**, then **Generate reports** (once per saved run) and download `incidents.csv`, `clusters.csv` and `report.pdf`.
   - **History & Reports** lists saved runs and offers downloads of registered reports that still exist.
   - Reports can only be generated for runs saved in the current session; the history stores parameters, not results.
   - The CSVs keep the original text exactly, so open untrusted CSVs in spreadsheet software with care: cells starting with `=`, `+`, `-` or `@` may run as formulas.

Settings (history database and reports folder) can be redirected with environment variables; see [.env.example](.env.example).

## Synthetic demonstration data
`data/sample/synthetic_demo.csv` is **entirely artificial**. It contains 35 made-up records (IDs `SYN-…`) placed around two invented zones plus three isolated points. It exists only to demonstrate and test the application. Its clusters, densities and categories say **nothing** about real incidents or real geographic risk. With the default settings it gives:
- two clusters (24 and 8 incidents; only the first meets the candidate size rule);
- three noise points.

Every incident, including the noise points, lands on a "high-density" KDE node. That is a known limitation (item 1 below), not a finding. Details: [data/sample/README.md](data/sample/README.md).

## Known limitations
The four tracked open items (see [docs/development_plan.md](docs/development_plan.md) → *Open items*; the PDF report states the same):
1. **KDE density-threshold method:** the high-density threshold is a quantile of all grid cells, including empty padding, so it can be low enough that isolated incidents count as "high density". Treat it as relative to one analysis and grid.
2. **Mixed time zones:** dates with different UTC offsets trigger a pandas warning in validation and are left as text-like values. Date counts convert them to UTC.
3. **Dataset identity and provenance:** the history identifies an input only by its file name, and density results don't carry incident IDs. Different files with the same name can't be told apart.
4. **Fixed algorithm constants:** results also depend on code constants that aren't part of the saved configuration (e.g. the KDE grid padding and cell cap).

Also:
- No real-world dataset has been selected; parameter defaults are placeholders.
- Performance at the 500,000-row limit is unverified.
- The PDF contains no maps.

## Docs
- [Requirements](docs/project_requirements.md)
- [Architecture](docs/system_architecture.md)
- [Dataset specification](docs/dataset_specification.md)
- [Module interfaces](docs/module_interfaces.md)
- [Development plan](docs/development_plan.md)
