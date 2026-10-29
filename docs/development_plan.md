# Development Plan

| # | Stage | Lead | Deliverable | Status |
|---|---|---|---|---|
| 1 | Foundation | All | Structure, config, contracts, interface stubs, docs | Done (`2344e64`) |
| 2 | Dataset selection + validation | M1 | Verified dataset (source, licence) or a clearly labelled synthetic set; `load_raw_dataset`, `validate_and_clean`, quality report | Loading and validation done (`05cddbf`). **Dataset selection still open.** |
| 3 | Data page + base map | M4 (M1) | Upload page, quality table, incident point map | Done (`5fc55b3`) |
| 4 | DBSCAN | M2 | `run_dbscan`, `haversine_m`, documented candidate-hotspot criteria, parameter-sensitivity notes | Done (`230dbc5`). Parameter-sensitivity notes and threshold justification need a real dataset. |
| 5 | KDE | M3 | `run_kde`, bandwidth rationale, high-density threshold | Done (`c8c2238`). Bandwidth rationale needs a real dataset. |
| 6 | Spatial statistics + method comparison | M3, M5 | `summarize`; overlap of DBSCAN clusters with KDE high-density cells | Done: point-based overlap (the commit following `c8c2238`). |
| 7 | Cluster/density maps + dashboard | M4 | Cluster and heat layers, Plotly charts, filters | Not started |
| 8 | Orchestration + history | M5 | `run_analysis`, SQLite history page, end-to-end test | Not started |
| 9 | Reports | M5 | CSV + PDF with parameters and limitations | Not started |
| 10 | Evaluation + final verification | All | Sensitivity analysis, full test run, docs updated to match the code, demo | Not started |

## Responsibilities
- **M1 – Data management:** stages 2–3 (data side), `data_manager`, `data_validator`, dataset documentation.
- **M2 – DBSCAN:** stage 4, `dbscan_analysis`, `test_dbscan.py`. Also implements `haversine_m`, which stays in `spatial_statistics.py` (owned by M3/M5) and is used through its documented signature.
- **M3 – KDE:** stages 5–6, `density_analysis`, part of `spatial_statistics`, `test_density_analysis.py`.
- **M4 – GIS and dashboard:** stages 3 and 7, `map_visualization`, `dashboard`.
- **M5 – Integration, reporting and evaluation:** stages 6, 8 and 9, `app_controller`, `database`, `report_generator`, `test_integration.py`.

**Everyone:** writes tests for their own module, reviews one other member's pull requests, keeps the docs accurate, and takes part in stage 10.

## Working agreement
- One branch per feature (`m2/dbscan-core`), merged to `main` by pull request with one reviewer, and only after `pytest` passes.
- Contract changes (`contracts.py`, `settings.py`) need agreement from every affected owner.
- A stage is done only when its skip-marked tests have been turned on and pass.
