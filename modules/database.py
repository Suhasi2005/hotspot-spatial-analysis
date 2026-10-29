"""SQLite analysis history. Owner: Member 5 (Integration).

Stores run metadata and parameters only (not raw incident rows). Uses the
standard-library sqlite3 module; the path comes from config.settings.DB_PATH.
Every function takes db_path so tests and checks can use a temporary database.
Errors are never swallowed: sqlite3.Error / OSError / ValueError propagate.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from config.settings import (
    DB_PATH,
    REPORTS_DIR,
    AnalysisConfig,
    CandidateHotspotCriteria,
    DBSCANParams,
    KDEParams,
    StudyArea,
)
from modules.contracts import AnalysisRun

CONFIG_SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id            TEXT PRIMARY KEY,
    created_at        TEXT NOT NULL,          -- ISO-8601 UTC
    source_name       TEXT NOT NULL,
    total_rows        INTEGER NOT NULL,
    valid_rows        INTEGER NOT NULL,
    config_json       TEXT NOT NULL,          -- serialized AnalysisConfig
    cluster_count     INTEGER,
    candidate_hotspot_count INTEGER,
    noise_count       INTEGER,
    report_paths_json TEXT                    -- generated CSV/PDF paths
);
"""

_COLUMNS = (
    "run_id", "created_at", "source_name", "total_rows", "valid_rows", "config_json",
    "cluster_count", "candidate_hotspot_count", "noise_count", "report_paths_json",
)


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the parent folder and the history table if absent (safe to repeat)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)


def save_run(run: AnalysisRun, db_path: Path = DB_PATH) -> None:
    """Insert one run's metadata (creating the schema if needed).

    created_at must be timezone-aware; it is stored as UTC ISO-8601 with
    microseconds so text order equals time order. Cluster columns are NULL
    when DBSCAN did not run. report_paths_json starts NULL; set_report_paths
    fills it once when reports are generated.
    A duplicate run_id raises sqlite3.IntegrityError.
    """
    row = (
        run.run_id,
        _utc_iso(run.created_at),
        run.dataset.source_name,
        run.dataset.report.total_rows,
        run.dataset.report.valid_rows,
        config_to_json(run.config),
        None if run.clusters is None else len(run.clusters.clusters),
        None if run.clusters is None else sum(1 for c in run.clusters.clusters if c.is_candidate_hotspot),
        None if run.clusters is None else run.clusters.noise_count,
        None,
    )
    init_db(db_path)
    with _connect(Path(db_path)) as conn:
        conn.execute(f"INSERT INTO analysis_runs ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})", row)


def list_runs(limit: int = 50, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Recent runs, newest first (created_at, then run_id, descending).

    Opens the database read-only and never creates it: a missing file returns
    []. Each dict has the table columns, except config_json is decoded into
    "config" (an AnalysisConfig equal to the one saved) and report_paths_json
    into "report_paths" (list or None). A file without the history table
    raises sqlite3.OperationalError.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit must be an integer >= 1 (got {limit!r}).")
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with _connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM analysis_runs ORDER BY created_at DESC, run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_decode_row(values) for values in rows]


def _decode_row(values: tuple) -> dict[str, Any]:
    record = dict(zip(_COLUMNS, values))
    record["config"] = config_from_json(record.pop("config_json"))
    paths = record.pop("report_paths_json")
    record["report_paths"] = None if paths is None else json.loads(paths)
    return record


def get_run(run_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    """One saved run in the list_runs format, or None if absent (read-only; never creates the file)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _connect(db_path, read_only=True) as conn:
        values = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM analysis_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return None if values is None else _decode_row(values)


def set_report_paths(
    run_id: str,
    paths: list[Path],
    db_path: Path = DB_PATH,
    *,
    reports_dir: Path = REPORTS_DIR,
) -> list[str]:
    """Register report files for an existing run whose report paths are not set yet.

    Each path must lie inside `reports_dir`; it is stored relative to it as a
    POSIX string (e.g. "<run_id>/report.pdf") in report_paths_json, so
    list_runs keeps returning a list of strings. Raises ValueError for an
    empty list or a path outside reports_dir, LookupError for an unknown
    run_id, and ValueError if paths are already registered. The update is a
    single parameterized statement guarded by "report_paths_json IS NULL".
    Returns the stored strings.
    """
    if not paths:
        raise ValueError("At least one report path is required.")
    root = Path(reports_dir).resolve()
    stored = []
    for path in paths:
        resolved = Path(path).resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            raise ValueError(f"Report path {path} is outside the reports folder.") from None
        stored.append(relative.as_posix())
    db_path = Path(db_path)
    if not db_path.exists():
        raise LookupError(f"Unknown run {run_id!r}: no history database.")
    with _connect(db_path) as conn:
        updated = conn.execute(
            "UPDATE analysis_runs SET report_paths_json = ? WHERE run_id = ? AND report_paths_json IS NULL",
            (json.dumps(stored), run_id),
        ).rowcount
        if updated != 1:
            exists = conn.execute("SELECT 1 FROM analysis_runs WHERE run_id = ?", (run_id,)).fetchone()
            if exists is None:
                raise LookupError(f"Unknown run {run_id!r}.")
            raise ValueError(f"Reports are already registered for run {run_id!r}.")
    return stored


def resolve_report_path(stored: str, reports_dir: Path = REPORTS_DIR) -> Path:
    """Absolute path of a stored report path, refusing anything outside reports_dir."""
    candidate = Path(stored)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Stored report path {stored!r} is not a plain relative path.")
    root = Path(reports_dir).resolve()
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Stored report path {stored!r} points outside the reports folder.")
    return resolved


def config_to_json(config: AnalysisConfig) -> str:
    """Exact JSON form of every AnalysisConfig field (floats round-trip exactly; NaN refused)."""
    return json.dumps({"schema_version": CONFIG_SCHEMA_VERSION, "config": asdict(config)},
                      sort_keys=True, allow_nan=False)


def config_from_json(text: str) -> AnalysisConfig:
    """Inverse of config_to_json; raises ValueError for an unknown schema version."""
    payload = json.loads(text)
    if payload.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise ValueError(f"Unsupported config schema_version {payload.get('schema_version')!r}.")
    c = payload["config"]
    return AnalysisConfig(
        dbscan=DBSCANParams(**c["dbscan"]),
        kde=KDEParams(**c["kde"]),
        hotspot=CandidateHotspotCriteria(**c["hotspot"]),
        study_area=None if c["study_area"] is None else StudyArea(**c["study_area"]),
        random_seed=c["random_seed"],
    )


@contextmanager
def _connect(db_path: Path, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Connection that commits on success, rolls back on error, and is always closed."""
    if read_only:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware (UTC).")
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")
