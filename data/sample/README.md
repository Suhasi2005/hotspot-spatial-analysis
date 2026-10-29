# Sample data

No real-world dataset has been selected yet. Dataset selection and verification remain open (Stage 2, see `docs/development_plan.md`).

Any file placed here must record its source, licence, date retrieved and whether it is real or synthetic. Synthetic files must say `synthetic` in the filename.

## `synthetic_demo.csv`
| | |
|---|---|
| Real or synthetic | **Synthetic.** Every record is artificial; none describes a real incident. |
| Source | Generated deterministically for this project (no random numbers): points placed on rings around two invented zone centres, plus three isolated points |
| Licence | Project-internal demonstration data |
| Created | 2026-10-30 |
| Records | 35 (IDs `SYN-A01`–`SYN-A24`, `SYN-B01`–`SYN-B08`, `SYN-N01`–`SYN-N03`) |
| Columns | `incident_id`, `latitude`, `longitude`, `severity`, `incident_type`, `incident_date` (ISO 8601, January–June 2024), `location_name` |
| Purpose | Demonstrating and testing the maps, clustering, density, summary charts and reports |

The coordinates sit in the Ahmedabad area only so that the basemap shows a familiar city. The zones, severities, types and dates are invented. **Results from this file say nothing about real geographic risk.**

**Observed with the default configuration** (`eps_m` 250, `min_samples` 5, `min_incidents` 10, `bandwidth_m` 300, `grid_cell_m` 100, quantile 0.95):
- 35 accepted, 0 rejected;
- DBSCAN cluster 0 = the 24 `SYN-A` records, a candidate hotspot;
- cluster 1 = the 8 `SYN-B` records, below the candidate size;
- 3 noise points (`SYN-N01`–`N03`);
- all 35 incidents fall on "high-density" KDE nodes, including the noise points. This illustrates the open density-threshold issue (development plan, Open item 1).
