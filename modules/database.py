"""SQLite analysis history. Owner: Member 5 (Integration).

Stores run metadata and parameters only (not raw incident rows). Uses the
standard-library sqlite3 module; the path comes from config.settings.DB_PATH.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config.settings import DB_PATH
from modules.contracts import AnalysisRun

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


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the history schema if absent. Stage 8."""
    raise NotImplementedError("Stage 8: database.init_db")


def save_run(run: AnalysisRun, db_path: Path = DB_PATH) -> None:
    """Persist one run's metadata. Stage 8."""
    raise NotImplementedError("Stage 8: database.save_run")


def list_runs(limit: int = 50, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return recent runs, newest first. Stage 8."""
    raise NotImplementedError("Stage 8: database.list_runs")
