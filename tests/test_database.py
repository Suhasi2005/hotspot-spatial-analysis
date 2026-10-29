"""SQLite history tests. Every test uses a temporary database under tmp_path."""

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from config.settings import (
    DEFAULT_ANALYSIS_CONFIG,
    AnalysisConfig,
    CandidateHotspotCriteria,
    DBSCANParams,
    KDEParams,
    StudyArea,
)
from modules.app_controller import cluster_dataset, estimate_density, summarize_results
from modules.contracts import AnalysisRun
from modules.data_validator import validate_and_clean
from modules.database import config_from_json, config_to_json, init_db, list_runs, save_run

T0 = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc)


def _dataset(usable=True):
    if not usable:
        raw = pd.DataFrame({"incident_id": [""], "latitude": ["1"], "longitude": ["2"]}, dtype=str)
        return validate_and_clean(raw, "unusable.csv")
    pts = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + \
          [(23.1, 72.65)]
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(len(pts))],
                        "latitude": [repr(p[0]) for p in pts], "longitude": [repr(p[1]) for p in pts]}, dtype=str)
    return validate_and_clean(raw, "synthetic.csv")


def _run(run_id="r1", created_at=T0, usable=True, config=DEFAULT_ANALYSIS_CONFIG):
    dataset = _dataset(usable)
    if not usable:
        return AnalysisRun(run_id, created_at, config, dataset, None, None, None)
    clusters = cluster_dataset(dataset, config)
    density = estimate_density(dataset, config)
    return AnalysisRun(run_id, created_at, config, dataset, clusters, density,
                       summarize_results(dataset, clusters, density))


# --- schema -------------------------------------------------------------------------


def test_init_db_creates_folder_and_table_and_is_repeatable(tmp_path):
    db = tmp_path / "nested" / "dir" / "history.sqlite3"
    init_db(db)
    init_db(db)                                                         # second call is a no-op
    with sqlite3.connect(db) as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert tables == [("analysis_runs",)]


# --- configuration round trip ------------------------------------------------------------


@pytest.mark.parametrize(
    "config",
    [
        DEFAULT_ANALYSIS_CONFIG,
        AnalysisConfig(
            dbscan=DBSCANParams(eps_m=0.1 + 0.2, min_samples=7),
            kde=KDEParams(bandwidth_m=123.456789012345, kernel="epanechnikov", grid_cell_m=33.3,
                          high_density_quantile=0.9),
            hotspot=CandidateHotspotCriteria(min_incidents=3, min_density_per_km2=12.5),
            study_area=StudyArea("box", 22.9, 23.2, 72.4, 72.7),
            random_seed=7,
        ),
    ],
    ids=["default", "non-default"],
)
def test_config_round_trip_is_exact(config):
    restored = config_from_json(config_to_json(config))
    assert restored == config                                            # every field, exact float equality
    assert type(restored.dbscan.min_samples) is int and type(restored.dbscan.eps_m) is float
    assert restored.dbscan.eps_m.hex() == config.dbscan.eps_m.hex()     # bit-for-bit (0.30000000000000004 case)


def test_config_with_nan_is_refused_before_anything_is_written(tmp_path):
    db = tmp_path / "h.sqlite3"
    bad = AnalysisConfig(dbscan=DBSCANParams(eps_m=float("nan")))      # construction allows NaN
    with pytest.raises(ValueError):
        config_to_json(bad)
    run = _run(usable=False, config=bad)
    with pytest.raises(ValueError):
        save_run(run, db)
    assert not db.exists()


def test_unknown_config_schema_version_is_rejected():
    with pytest.raises(ValueError, match="schema_version"):
        config_from_json('{"schema_version": 99, "config": {}}')


# --- save / list -------------------------------------------------------------------------


def test_save_and_list_round_trip(tmp_path):
    db = tmp_path / "h.sqlite3"
    run = _run()
    save_run(run, db)
    (row,) = list_runs(db_path=db)
    assert row["run_id"] == "r1" and row["source_name"] == "synthetic.csv"
    assert row["created_at"] == "2026-01-02T03:04:05.678901+00:00"
    assert (row["total_rows"], row["valid_rows"]) == (19, 19)
    assert row["cluster_count"] == len(run.clusters.clusters) == 2
    assert row["candidate_hotspot_count"] == sum(c.is_candidate_hotspot for c in run.clusters.clusters)
    assert row["noise_count"] == run.clusters.noise_count == 1
    assert row["config"] == run.config and row["report_paths"] is None
    assert set(row) == {"run_id", "created_at", "source_name", "total_rows", "valid_rows", "cluster_count",
                        "candidate_hotspot_count", "noise_count", "config", "report_paths"}


def test_unusable_run_is_saved_with_null_result_columns(tmp_path):
    db = tmp_path / "h.sqlite3"
    save_run(_run(usable=False), db)
    (row,) = list_runs(db_path=db)
    assert (row["valid_rows"], row["total_rows"]) == (0, 1)
    assert (row["cluster_count"], row["candidate_hotspot_count"], row["noise_count"]) == (None, None, None)


def test_created_at_is_stored_as_utc_from_any_offset(tmp_path):
    db = tmp_path / "h.sqlite3"
    ist = timezone(timedelta(hours=5, minutes=30))
    save_run(_run(created_at=datetime(2026, 1, 2, 8, 34, 5, 0, tzinfo=ist), usable=False), db)
    assert list_runs(db_path=db)[0]["created_at"] == "2026-01-02T03:04:05.000000+00:00"


def test_naive_created_at_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        save_run(_run(created_at=datetime(2026, 1, 2), usable=False), tmp_path / "h.sqlite3")


def test_runs_are_listed_newest_first_with_limit(tmp_path):
    db = tmp_path / "h.sqlite3"
    for i, rid in enumerate(["a", "b", "c", "d"]):
        save_run(_run(run_id=rid, created_at=T0 + timedelta(seconds=i), usable=False), db)
    save_run(_run(run_id="e", created_at=T0 + timedelta(seconds=3), usable=False), db)   # ties with "d"
    assert [r["run_id"] for r in list_runs(db_path=db)] == ["e", "d", "c", "b", "a"]
    assert [r["run_id"] for r in list_runs(limit=2, db_path=db)] == ["e", "d"]


@pytest.mark.parametrize("limit", [0, -1, 2.5, True, "5"])
def test_invalid_limit_is_rejected(tmp_path, limit):
    with pytest.raises(ValueError, match="limit"):
        list_runs(limit=limit, db_path=tmp_path / "h.sqlite3")


def test_duplicate_run_id_raises(tmp_path):
    db = tmp_path / "h.sqlite3"
    save_run(_run(usable=False), db)
    with pytest.raises(sqlite3.IntegrityError):
        save_run(_run(usable=False), db)
    assert len(list_runs(db_path=db)) == 1                              # failed insert rolled back


# --- isolation and errors -------------------------------------------------------------------


def test_listing_a_missing_database_returns_empty_and_creates_nothing(tmp_path):
    db = tmp_path / "missing" / "h.sqlite3"
    assert list_runs(db_path=db) == []
    assert not db.exists() and not db.parent.exists()


def test_foreign_database_without_history_table_is_an_error(tmp_path):
    db = tmp_path / "other.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE something_else (x INTEGER)")
    conn.close()
    with pytest.raises(sqlite3.OperationalError, match="analysis_runs"):
        list_runs(db_path=db)


def test_unwritable_path_raises(tmp_path):
    folder_as_db = tmp_path / "a_folder"
    folder_as_db.mkdir()
    with pytest.raises(sqlite3.OperationalError):
        save_run(_run(usable=False), folder_as_db)


def test_connections_are_closed(tmp_path):
    """On Windows an open SQLite connection locks the file; deleting it proves closure."""
    db = tmp_path / "h.sqlite3"
    save_run(_run(usable=False), db)
    list_runs(db_path=db)
    with pytest.raises(sqlite3.IntegrityError):
        save_run(_run(usable=False), db)                                # error path must close too
    os.remove(db)
    assert not db.exists()


def test_save_does_not_mutate_the_run(tmp_path):
    run = _run()
    frame_before = run.dataset.frame.copy(deep=True)
    labels_before = run.clusters.labeled_frame.copy(deep=True)
    summary_before = run.summary
    save_run(run, tmp_path / "h.sqlite3")
    pd.testing.assert_frame_equal(run.dataset.frame, frame_before)
    pd.testing.assert_frame_equal(run.clusters.labeled_frame, labels_before)
    assert run.summary is summary_before and run.run_id == "r1" and run.created_at == T0


# --- Stage 9: report paths ---------------------------------------------------------------------

from modules.database import get_run, resolve_report_path, set_report_paths  # noqa: E402


def _saved(tmp_path, run_id="r1"):
    db = tmp_path / "h.sqlite3"
    save_run(_run(run_id=run_id, usable=False), db)
    reports = tmp_path / "reports"
    files = [reports / run_id / name for name in ("incidents.csv", "clusters.csv", "report.pdf")]
    return db, reports, files


def test_report_paths_round_trip_as_relative_strings(tmp_path):
    db, reports, files = _saved(tmp_path)
    stored = set_report_paths("r1", files, db, reports_dir=reports)
    assert stored == ["r1/incidents.csv", "r1/clusters.csv", "r1/report.pdf"]
    assert list_runs(db_path=db)[0]["report_paths"] == stored                       # list of strings, as before
    assert get_run("r1", db)["report_paths"] == stored
    assert [resolve_report_path(s, reports) for s in stored] == [f.resolve() for f in files]


def test_report_paths_are_set_only_once_and_only_for_known_runs(tmp_path):
    db, reports, files = _saved(tmp_path)
    with pytest.raises(LookupError, match="Unknown run"):
        set_report_paths("nope", files, db, reports_dir=reports)
    set_report_paths("r1", files, db, reports_dir=reports)
    with pytest.raises(ValueError, match="already registered"):
        set_report_paths("r1", files[:1], db, reports_dir=reports)
    assert get_run("r1", db)["report_paths"] == ["r1/incidents.csv", "r1/clusters.csv", "r1/report.pdf"]


def test_report_paths_outside_the_reports_folder_are_refused(tmp_path):
    db, reports, files = _saved(tmp_path)
    for bad in (tmp_path / "elsewhere.pdf", reports / ".." / "escape.pdf"):
        with pytest.raises(ValueError, match="outside the reports folder"):
            set_report_paths("r1", [bad], db, reports_dir=reports)
    with pytest.raises(ValueError, match="At least one"):
        set_report_paths("r1", [], db, reports_dir=reports)
    assert get_run("r1", db)["report_paths"] is None


def test_set_report_paths_on_missing_database_creates_nothing(tmp_path):
    db = tmp_path / "missing.sqlite3"
    with pytest.raises(LookupError):
        set_report_paths("r1", [tmp_path / "r" / "x.pdf"], db, reports_dir=tmp_path / "r")
    assert not db.exists()


@pytest.mark.parametrize("stored", ["../escape.pdf", "r1/../../escape.pdf", "/abs/report.pdf", "C:/abs/report.pdf"])
def test_resolve_report_path_rejects_traversal_and_absolute_paths(tmp_path, stored):
    with pytest.raises(ValueError):
        resolve_report_path(stored, tmp_path / "reports")


def test_get_run_is_read_only(tmp_path):
    missing = tmp_path / "none.sqlite3"
    assert get_run("r1", missing) is None and not missing.exists()
    db, _, _ = _saved(tmp_path)
    assert get_run("unknown", db) is None
    assert get_run("r1", db)["run_id"] == "r1"
