"""Data page state tests (redesign Stage 2).

Each state runs through the real page and the real validator. Files are chosen
through the sample selector, which shares its load path with the uploader.
Temporary files and storage only.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from config.settings import OPTIONAL_COLUMNS, REQUIRED_COLUMNS
from modules.dashboard import SOURCE_MODE_KEY, SOURCE_OPTIONS
from modules.ui_components import BADGE_COLOURS

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page('Data')\n"
HEADER = "incident_id,latitude,longitude"
GOOD = [f"P{i},23.02{i},72.57{i}" for i in range(6)]
FILES = {
    "valid_full.csv": ["incident_id,latitude,longitude,severity", *[f"{row},minor" for row in GOOD]],
    "required_only.csv": [HEADER, *GOOD],
    "some_rejected.csv": [HEADER, *GOOD, "BAD1,999,72.5", "BAD2,23.0,999"],
    "none_usable.csv": [HEADER, "BAD1,999,72.5", "BAD2,999,72.6"],
    "wrong_columns.csv": ["name,value", "a,1"],
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")
    for name, lines in FILES.items():
        (tmp_path / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _empty():
    at = AppTest.from_string(SCRIPT, default_timeout=120).run()
    assert not at.exception
    return at


def _load(tmp_path, monkeypatch, name):
    monkeypatch.setattr(dashboard, "list_sample_datasets", lambda: [tmp_path / name])
    at = _empty()
    at.radio(key=SOURCE_MODE_KEY).set_value(SOURCE_OPTIONS[1]).run()
    assert not at.exception
    return at


def _metrics(at):
    return {m.label: m.value for m in at.metric}


def _text(at):
    return " ".join(m.value for m in at.markdown)


def test_no_dataset_shows_the_upload_workspace_and_format():
    at = _empty()
    text = _text(at)
    assert "Load incident data" in text and "Accepted CSV format" in text
    for column in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS):
        assert f"`{column}`" in text
    assert [r.label for r in at.radio] == ["Source"] and len(at.metric) == 0 and not at.tabs
    assert "dataset" not in at.session_state


def test_valid_dataset_replaces_the_workspace_with_the_compact_bar(tmp_path, monkeypatch):
    at = _load(tmp_path, monkeypatch, "valid_full.csv")
    text = _text(at)
    assert "valid\\_full\\.csv" in text and "Load incident data" not in text
    assert any("6 rows · 6 accepted · 0 rejected" in c.value for c in at.caption)
    assert ":green-badge[Ready]" in text
    assert _metrics(at) == {"Rows in file": "6", "Accepted": "6", "Rejected": "0", "Validation status": "Ready"}
    assert [t.label for t in at.tabs] == ["Incident Map", "Validation Issues (0)", "Data Preview"]
    change = next(e for e in at.main.expander if e.label == "Change dataset")
    assert change.proto.expanded is False
    assert any("ready for analysis" in s.value for s in at.success)


def test_rejected_rows_show_a_warning_badge_and_the_issues(tmp_path, monkeypatch):
    at = _load(tmp_path, monkeypatch, "some_rejected.csv")
    assert _metrics(at)["Rejected"] == "2" and _metrics(at)["Validation status"] == "Ready with rejections"
    assert ":orange-badge[Ready with rejections]" in _text(at)
    assert any("2 row(s) were rejected" in w.value for w in at.warning)
    assert at.tabs[1].label.startswith("Validation Issues (") and at.tabs[1].label != "Validation Issues (0)"
    assert len(at.dataframe) == 2                                        # issues + preview
    assert at.dataframe[1].value.index.tolist() == list(range(6))        # Source Row data unchanged


def test_unusable_dataset_keeps_the_way_to_change_it_open(tmp_path, monkeypatch):
    at = _load(tmp_path, monkeypatch, "none_usable.csv")
    assert _metrics(at)["Validation status"] == "Unusable" and _metrics(at)["Accepted"] == "0"
    assert any("unusable" in e.value for e in at.error)
    assert next(e for e in at.main.expander if e.label == "Change dataset").proto.expanded is True
    assert any("No accepted rows to preview." in c.value for c in at.caption)


def test_file_that_cannot_be_loaded_stays_on_the_workspace_with_its_error(tmp_path, monkeypatch):
    at = _load(tmp_path, monkeypatch, "wrong_columns.csv")
    assert any("This file cannot be used" in e.value for e in at.error)
    assert "Load incident data" in _text(at) and len(at.metric) == 0 and "dataset" not in at.session_state


def test_missing_optional_columns_are_reported_not_rejected(tmp_path, monkeypatch):
    at = _load(tmp_path, monkeypatch, "required_only.csv")
    assert _metrics(at)["Validation status"] == "Ready"
    assert any("Optional columns present: none." in c.value for c in at.caption)


def test_every_status_tone_has_a_badge_colour():
    assert set(BADGE_COLOURS) == {"success", "warning", "error", "info"}
