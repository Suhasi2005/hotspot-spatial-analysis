# Development Plan

| # | Stage | Lead | Deliverable | Status |
|---|---|---|---|---|
| 1 | Foundation | All | Structure, config, contracts, interface stubs, docs | Done (`2344e64`) |
| 2 | Dataset selection + validation | M1 | Verified dataset (source, licence) or a clearly labelled synthetic set; `load_raw_dataset`, `validate_and_clean`, quality report | Loading and validation done (`05cddbf`). **Dataset selection still open.** |
| 3 | Data page + base map | M4 (M1) | Upload page, quality table, incident point map | Done (`5fc55b3`) |
| 4 | DBSCAN | M2 | `run_dbscan`, `haversine_m`, documented candidate-hotspot criteria, parameter-sensitivity notes | Done (`230dbc5`). Parameter-sensitivity notes and threshold justification need a real dataset. |
| 5 | KDE | M3 | `run_kde`, bandwidth rationale, high-density threshold | Done (`c8c2238`). Bandwidth rationale needs a real dataset. |
| 6 | Spatial statistics + method comparison | M3, M5 | `summarize`; overlap of DBSCAN clusters with KDE high-density cells | Done (`ec81f8d`): point-based overlap. |
| 7 | Cluster/density maps + dashboard | M4 | Cluster and heat layers, Plotly charts, filters | Done (`e054d97`): KDE grid image overlay, cluster map with all circles, display-only filters. |
| 8 | Orchestration + history | M5 | `run_analysis`, SQLite history page, end-to-end test | Done (the commit following `e054d97`): `run_analysis`, `record_run` with configuration checks, SQLite history page. |
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

## Open items (deferred; behaviour unchanged until separately approved)
1. **KDE high-density threshold methodology (Stages 5 and 7).**
   - `high_density_threshold` is the `high_density_quantile` (default 0.95) of **all** grid cells, and the data-extent grid is mostly empty padding. So the threshold is low, and even isolated single incidents can exceed it. A synthetic run reported "noise at high density: 100%".
   - The maps, the comparison table and the notes report this faithfully, but conclusions about "high-density" areas should not be drawn from it yet.
   - Any change, for example a quantile over cells near incidents only, needs separate approval. It would change the Stage 5 analysis and the Stage 7 threshold layer.
2. **Mixed time-zone warning in the Stage 2 validator.**
   - When `incident_date` values carry different UTC offsets, `validate_and_clean` triggers a pandas `FutureWarning` and leaves the column as objects instead of `datetime64`.
   - `incidents_by_period` (Stage 7) already handles this by converting to UTC. The validator itself is unchanged and is tracked separately.
3. **Dataset identity in the history (Stage 8).**
   - History rows identify the input only by `source_name`, so two different files with the same name can't be told apart.
   - A file hash or other provenance was deferred in Stage 6 and remains deferred until approved.
4. **Fixed algorithm constants are not part of the saved configuration (reproducibility).**
   - History rows store every `AnalysisConfig` field exactly. Results also depend on code constants that aren't in the configuration:
     - `PAD_BANDWIDTHS` (3), which sets the KDE data-extent grid and therefore the high-density threshold;
     - `MAX_GRID_CELLS`, which decides whether KDE runs at all;
     - the Web Mercator and earth-radius conventions.
   - If these constants change, a saved row's configuration alone no longer reproduces its results.
   - Algorithm or code versioning is deferred until approved.
