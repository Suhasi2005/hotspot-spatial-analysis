# Hotspot Identification and Spatial Analysis

A Streamlit GIS application that validates point-incident data, finds spatial clusters (geodesic DBSCAN), estimates density (haversine KDE), and reports the results. The first demonstration domain is road accidents, but the design works for any point-incident data.

**Status: Stage 1 — foundation only.** The app opens and its navigation works, but every analysis page is a placeholder. See [docs/development_plan.md](docs/development_plan.md).

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
Use `python -m ...` so the commands use the venv's packages. The system Python on a shared machine may not have them.

## Docs
- [Requirements](docs/project_requirements.md)
- [Architecture](docs/system_architecture.md)
- [Dataset specification](docs/dataset_specification.md)
- [Module interfaces](docs/module_interfaces.md)
- [Development plan](docs/development_plan.md)

## Important caveat
DBSCAN clusters, KDE high-density areas and "candidate hotspots" are descriptive results. They are **not** statistically significant hotspots.
