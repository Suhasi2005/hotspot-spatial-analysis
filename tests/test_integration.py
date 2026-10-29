"""Structural integration checks: every module imports and exposes its contract."""

import ast
import importlib
from pathlib import Path

import pytest

MODULE_CONTRACTS = {
    "modules.data_manager": ["list_sample_datasets", "load_raw_dataset"],
    "modules.data_validator": ["validate_and_clean", "summarize_quality"],
    "modules.dbscan_analysis": ["run_dbscan", "metres_to_radians"],
    "modules.density_analysis": ["run_kde"],
    "modules.spatial_statistics": ["summarize", "compare_methods", "haversine_m", "incidents_by_period"],
    "modules.map_visualization": [
        "build_incident_map", "build_cluster_map", "build_density_map",
        "cluster_marker_records", "density_overlay_rgba", "density_overlay_bounds",
    ],
    "modules.app_controller": [
        "load_and_validate", "cluster_dataset", "estimate_density", "summarize_results", "run_analysis",
        "record_run",
    ],
    "modules.database": ["init_db", "save_run", "list_runs", "config_to_json", "config_from_json"],
    "modules.report_generator": ["export_csv", "export_pdf"],
}


@pytest.mark.parametrize("module_name,functions", MODULE_CONTRACTS.items())
def test_module_exposes_contract(module_name, functions):
    module = importlib.import_module(module_name)
    for fn in functions:
        assert callable(getattr(module, fn)), f"{module_name}.{fn} missing"


def _imports_streamlit(source: str) -> bool:
    """True if the code (not comments/strings) imports streamlit in any form."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "streamlit" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "streamlit":
            return True
    return False


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import streamlit as st", True),
        ("from streamlit import session_state", True),
        ("from streamlit.testing.v1 import AppTest", True),
        ("import streamlit_folium", False),
        ("# import streamlit\nx = 'import streamlit'", False),
    ],
)
def test_streamlit_import_detector(source, expected):
    assert _imports_streamlit(source) is expected


def test_analysis_modules_do_not_import_streamlit():
    """Only dashboard.py may import Streamlit; business logic stays UI-free."""
    modules_dir = Path(__file__).resolve().parent.parent / "modules"
    offenders = [
        p.name
        for p in modules_dir.glob("*.py")
        if p.name != "dashboard.py" and _imports_streamlit(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# --- Stage 8: run_analysis, record_run and the history (temporary databases only) -------------

E2E_ROWS = (
    ["incident_id,latitude,longitude,severity"]
    + [f"A{i},{23.0200 + 0.0001 * i:.4f},72.5700,major" for i in range(12)]
    + [f"B{i},{23.0650 + 0.0001 * i:.4f},72.5800,minor" for i in range(6)]
    + ["N0,23.1000,72.6500,minor", "BAD,not-a-number,72.57,minor"]          # 1 noise, 1 rejected row
)


def _csv(tmp_path, rows=E2E_ROWS, name="synthetic_e2e.csv"):
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_end_to_end_pipeline_on_synthetic_data(tmp_path):
    """load -> validate -> DBSCAN -> KDE -> summary -> history row."""
    from config.settings import DEFAULT_ANALYSIS_CONFIG
    from modules.app_controller import run_analysis
    from modules.database import list_runs

    db = tmp_path / "history.sqlite3"
    run = run_analysis(_csv(tmp_path), DEFAULT_ANALYSIS_CONFIG, db_path=db)
    assert (run.dataset.report.total_rows, run.dataset.report.valid_rows) == (20, 19)
    assert len(run.clusters.clusters) == 2 and run.clusters.noise_count == 1
    assert run.density.params["n_points"] == 19
    assert run.summary.method_comparison.total_incidents == 19
    assert run.created_at.tzinfo is not None and len(run.run_id) == 32

    (row,) = list_runs(db_path=db)
    assert row["run_id"] == run.run_id and row["source_name"] == "synthetic_e2e.csv"
    assert (row["total_rows"], row["valid_rows"]) == (20, 19)
    assert (row["cluster_count"], row["noise_count"]) == (2, 1)
    assert row["candidate_hotspot_count"] == run.summary.candidate_hotspot_count
    assert row["config"] == DEFAULT_ANALYSIS_CONFIG


def test_persist_false_never_touches_the_database(tmp_path):
    from config.settings import DEFAULT_ANALYSIS_CONFIG
    from modules.app_controller import run_analysis

    db = tmp_path / "never" / "history.sqlite3"
    run = run_analysis(_csv(tmp_path), DEFAULT_ANALYSIS_CONFIG, persist=False, db_path=db)
    assert run.summary is not None and not db.exists() and not db.parent.exists()


def test_results_are_identical_with_and_without_persisting(tmp_path):
    from config.settings import DEFAULT_ANALYSIS_CONFIG
    from modules.app_controller import run_analysis

    saved = run_analysis(_csv(tmp_path), DEFAULT_ANALYSIS_CONFIG, db_path=tmp_path / "h.sqlite3")
    unsaved = run_analysis(_csv(tmp_path), DEFAULT_ANALYSIS_CONFIG, persist=False)
    assert saved.summary == unsaved.summary
    assert saved.clusters.labeled_frame.equals(unsaved.clusters.labeled_frame)
    assert (saved.density.density == unsaved.density.density).all()


def test_unusable_dataset_is_saved_with_null_results(tmp_path):
    from config.settings import DEFAULT_ANALYSIS_CONFIG
    from modules.app_controller import run_analysis
    from modules.database import list_runs

    db = tmp_path / "h.sqlite3"
    csv = _csv(tmp_path, ["incident_id,latitude,longitude", ",1,2", "B,x,2"], "unusable.csv")
    run = run_analysis(csv, DEFAULT_ANALYSIS_CONFIG, db_path=db)
    assert (run.clusters, run.density, run.summary) == (None, None, None)
    (row,) = list_runs(db_path=db)
    assert (row["valid_rows"], row["cluster_count"], row["candidate_hotspot_count"], row["noise_count"]) == (0, None, None, None)


@pytest.mark.parametrize("case", ["malformed", "kde_grid_cap", "dbscan_invalid"])
def test_failed_runs_raise_and_are_not_saved(tmp_path, case):
    from config.settings import AnalysisConfig, DBSCANParams, KDEParams
    from modules.app_controller import run_analysis
    from modules.contracts import AnalysisError, DataValidationError

    db = tmp_path / "h.sqlite3"
    csv, config, error = _csv(tmp_path), AnalysisConfig(), AnalysisError
    if case == "malformed":
        csv, error = _csv(tmp_path, ["incident_id,latitude,longitude", "A,1,2,EXTRA"], "bad.csv"), DataValidationError
    elif case == "kde_grid_cap":
        config = AnalysisConfig(kde=KDEParams(grid_cell_m=1.0))
    else:
        config = AnalysisConfig(dbscan=DBSCANParams(eps_m=float("nan")))
    with pytest.raises(error):
        run_analysis(csv, config, db_path=db)
    assert not db.exists()


def test_record_run_saves_complete_results_and_rejects_partial_or_mismatched(tmp_path):
    from config.settings import DEFAULT_ANALYSIS_CONFIG
    from modules.app_controller import record_run, run_analysis
    from modules.contracts import AnalysisError
    from modules.database import list_runs

    db = tmp_path / "h.sqlite3"
    base = run_analysis(_csv(tmp_path), DEFAULT_ANALYSIS_CONFIG, persist=False)
    args = (base.dataset, base.config, base.clusters, base.density, base.summary)
    saved = record_run(*args, db_path=db)
    assert [r["run_id"] for r in list_runs(db_path=db)] == [saved.run_id]
    assert saved.run_id != base.run_id and saved.summary is base.summary

    with pytest.raises(AnalysisError, match="complete runs"):
        record_run(base.dataset, base.config, base.clusters, None, base.summary, db_path=db)   # KDE failed
    other = run_analysis(_csv(tmp_path, E2E_ROWS[:15], "other.csv"), DEFAULT_ANALYSIS_CONFIG, persist=False)
    with pytest.raises(AnalysisError):
        record_run(base.dataset, base.config, base.clusters, base.density, other.summary, db_path=db)
    with pytest.raises(AnalysisError):
        record_run(other.dataset, base.config, base.clusters, base.density, base.summary, db_path=db)
    assert len(list_runs(db_path=db)) == 1                                  # nothing partial saved


def test_record_run_unusable_dataset_requires_empty_results(tmp_path):
    from config.settings import DEFAULT_ANALYSIS_CONFIG
    from modules.app_controller import record_run, run_analysis
    from modules.contracts import AnalysisError

    db = tmp_path / "h.sqlite3"
    unusable = run_analysis(_csv(tmp_path, ["incident_id,latitude,longitude", ",1,2"], "u.csv"),
                            DEFAULT_ANALYSIS_CONFIG, persist=False)
    record_run(unusable.dataset, DEFAULT_ANALYSIS_CONFIG, None, None, None, db_path=db)
    full = run_analysis(_csv(tmp_path), DEFAULT_ANALYSIS_CONFIG, persist=False)
    with pytest.raises(AnalysisError, match="unusable"):
        record_run(unusable.dataset, DEFAULT_ANALYSIS_CONFIG, full.clusters, None, None, db_path=db)


# --- record_run: configuration must match the results ---------------------------------------------

def _nondefault_config(study_area=True):
    from config.settings import AnalysisConfig, CandidateHotspotCriteria, DBSCANParams, KDEParams, StudyArea

    return AnalysisConfig(
        dbscan=DBSCANParams(eps_m=300.0, min_samples=4),
        kde=KDEParams(bandwidth_m=250.0, kernel="epanechnikov", grid_cell_m=80.0, high_density_quantile=0.9),
        hotspot=CandidateHotspotCriteria(min_incidents=7, min_density_per_km2=3.5),
        study_area=StudyArea("box", 22.99, 23.12, 72.55, 72.67) if study_area else None,
        random_seed=11,
    )


def _with(config, **changes):
    """Copy of a frozen AnalysisConfig with nested fields replaced, e.g. dbscan__eps_m=1.0."""
    from dataclasses import replace

    parts = {}
    for key, value in changes.items():
        group, _, field = key.partition("__")
        if field:
            parts[group] = replace(parts.get(group, getattr(config, group)), **{field: value})
        else:
            parts[group] = value
    return replace(config, **parts)


@pytest.mark.parametrize("study_area", [True, False], ids=["with-study-area", "data-extent"])
def test_record_run_accepts_matching_nondefault_configuration(tmp_path, study_area):
    from modules.app_controller import record_run, run_analysis
    from modules.database import list_runs

    config = _nondefault_config(study_area)
    base = run_analysis(_csv(tmp_path), config, persist=False)
    db = tmp_path / "h.sqlite3"
    saved = record_run(base.dataset, config, base.clusters, base.density, base.summary, db_path=db)
    (row,) = list_runs(db_path=db)
    assert row["run_id"] == saved.run_id and row["config"] == config


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"dbscan__eps_m": 301.0}, "dbscan.eps_m"),
        ({"dbscan__min_samples": 5}, "dbscan.min_samples"),
        ({"kde__bandwidth_m": 251.0}, "kde.bandwidth_m"),
        ({"kde__kernel": "gaussian"}, "kde.kernel"),
        ({"kde__grid_cell_m": 81.0}, "kde.grid_cell_m"),
        ({"kde__high_density_quantile": 0.95}, "kde.high_density_quantile"),
        ({"hotspot__min_incidents": 13}, "hotspot.min_incidents"),          # flips the 12-incident cluster
        ({"study_area": None}, "study_area"),                                 # results used a study area
        ({"study_area__max_lat": 23.13}, "study_area"),                       # different box
    ],
    ids=["eps_m", "min_samples", "bandwidth_m", "kernel", "grid_cell_m", "quantile", "min_incidents",
         "study-area-removed", "study-area-box"],
)
def test_record_run_rejects_each_configuration_mismatch_and_writes_nothing(tmp_path, changes, match):
    from modules.app_controller import record_run, run_analysis
    from modules.contracts import AnalysisError

    config = _nondefault_config()
    base = run_analysis(_csv(tmp_path), config, persist=False)
    db = tmp_path / "h.sqlite3"
    with pytest.raises(AnalysisError, match=match):
        record_run(base.dataset, _with(config, **changes), base.clusters, base.density, base.summary, db_path=db)
    assert not db.exists()                                                    # nothing persisted


def test_record_run_rejects_study_area_added_after_a_data_extent_run(tmp_path):
    from config.settings import StudyArea
    from modules.app_controller import record_run, run_analysis
    from modules.contracts import AnalysisError

    config = _nondefault_config(study_area=False)
    base = run_analysis(_csv(tmp_path), config, persist=False)
    db = tmp_path / "h.sqlite3"
    claimed = _with(config, study_area=StudyArea("box", 22.99, 23.12, 72.55, 72.67))
    with pytest.raises(AnalysisError, match="study_area"):
        record_run(base.dataset, claimed, base.clusters, base.density, base.summary, db_path=db)
    assert not db.exists()


def test_record_run_rejects_study_area_that_excludes_accepted_incidents(tmp_path):
    """Even with a matching KDE grid, a box that leaves accepted incidents outside is refused."""
    from dataclasses import replace

    from config.settings import StudyArea
    from modules.app_controller import record_run, run_analysis, summarize_results
    from modules.contracts import AnalysisError

    config = _nondefault_config()
    base = run_analysis(_csv(tmp_path), config, persist=False)
    narrow = StudyArea("narrow", 23.00, 23.05, 72.55, 72.67)                  # excludes the B group and N0
    density = replace(base.density, params={**base.density.params, "grid_extent": {
        "south": 23.00, "north": 23.05, "west": 72.55, "east": 72.67}})
    summary = summarize_results(base.dataset, base.clusters, density)         # consistent with that grid
    db = tmp_path / "h.sqlite3"
    with pytest.raises(AnalysisError, match="outside the configured box") as excinfo:
        record_run(base.dataset, _with(config, study_area=narrow), base.clusters, density, summary, db_path=db)
    assert "grid" not in str(excinfo.value).split("study_area:")[1]           # grid matched; only the box check failed
    assert not db.exists()


def test_record_run_reports_every_mismatch_at_once(tmp_path):
    from modules.app_controller import record_run, run_analysis
    from modules.contracts import AnalysisError

    config = _nondefault_config()
    base = run_analysis(_csv(tmp_path), config, persist=False)
    wrong = _with(config, dbscan__eps_m=1.0, kde__kernel="gaussian", hotspot__min_incidents=100)
    with pytest.raises(AnalysisError) as excinfo:
        record_run(base.dataset, wrong, base.clusters, base.density, base.summary, db_path=tmp_path / "h.sqlite3")
    message = str(excinfo.value)
    assert "dbscan.eps_m" in message and "kde.kernel" in message and "hotspot.min_incidents" in message


def test_record_run_dataset_mismatch_is_still_rejected_first(tmp_path):
    from modules.app_controller import record_run, run_analysis
    from modules.contracts import AnalysisError

    config = _nondefault_config()
    base = run_analysis(_csv(tmp_path), config, persist=False)
    other = run_analysis(_csv(tmp_path, E2E_ROWS[:15], "other.csv"), config, persist=False)
    db = tmp_path / "h.sqlite3"
    with pytest.raises(AnalysisError, match="does not match") as excinfo:     # Stage 6 dataset check
        record_run(other.dataset, config, base.clusters, base.density, base.summary, db_path=db)
    assert "Configuration does not match" not in str(excinfo.value)
    assert not db.exists()


def test_min_incidents_values_with_identical_flags_are_indistinguishable(tmp_path):
    """Documented limit: results record no criteria, so min_incidents is checked only through the
    candidate flags. Clusters of 12 and 6 incidents give identical flags for 7 and 8; both describe
    the same results, so both are accepted. min_density_per_km2 and random_seed affect no result."""
    from modules.app_controller import record_run, run_analysis

    config = _nondefault_config()
    base = run_analysis(_csv(tmp_path), config, persist=False)
    assert sorted(c.incident_count for c in base.clusters.clusters) == [6, 12]
    for i, changes in enumerate([{"hotspot__min_incidents": 8}, {"hotspot__min_density_per_km2": None},
                                 {"random_seed": 99}]):
        record_run(base.dataset, _with(config, **changes), base.clusters, base.density, base.summary,
                   db_path=tmp_path / f"h{i}.sqlite3")


def test_run_analysis_does_not_modify_the_source_file(tmp_path):
    from config.settings import DEFAULT_ANALYSIS_CONFIG
    from modules.app_controller import run_analysis

    csv = _csv(tmp_path)
    before = csv.read_bytes()
    run_analysis(csv, DEFAULT_ANALYSIS_CONFIG, db_path=tmp_path / "h.sqlite3")
    assert csv.read_bytes() == before
