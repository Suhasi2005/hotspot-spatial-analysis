"""History & Reports page tests (redesign Stage 6).

Layout, status and session behaviour only: database and report contents are covered
by their own tests. Synthetic data and temporary history/reports locations only.
"""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from modules.dashboard import CACHE_KEY, HISTORY_STORAGE_NOTE, SYNTHETIC_NOTICE, report_status
from modules.data_validator import validate_and_clean
from modules.database import get_run, list_runs
from modules.report_generator import CSV_SAFETY_WARNING

ROOT = Path(__file__).resolve().parent.parent
# One session across pages, the way the real app runs.
SCRIPT = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from modules.dashboard import render_page
render_page(st.session_state["page"])
"""
HISTORY, SUMMARY = "History & Reports", "Summary"


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    db, reports = tmp_path / "history.sqlite3", tmp_path / "reports"
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", db)
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", reports)
    return db, reports


def _dataset(name="field_export.csv"):
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(len(points))],
                        "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]}, dtype=str)
    return validate_and_clean(raw, name)


def _session(page=SUMMARY, name="field_export.csv"):
    at = AppTest.from_string(SCRIPT, default_timeout=120)
    at.session_state["page"] = page
    at.session_state["dataset"] = _dataset(name)
    return at.run()


def _go(at, page):
    at.session_state["page"] = page
    return at.run()


def _saved(name="field_export.csv"):
    at = _session(name=name)
    at.button(key="save_run").click().run()
    return at


def _select(at, run_id):
    return at.selectbox(key="history_report_run").set_value(run_id).run()


def _keys(at):
    return [b.key for b in at.button]


def _downloads(at):
    return [el.proto.label for el in at.get("download_button")]


def _metrics(at):
    return {m.label: m.value for m in at.metric}


def _text(at):
    return " ".join(m.value for m in at.main.markdown) + " " + " ".join(c.value for c in at.main.caption)


def _run_id(at):
    return at.session_state[CACHE_KEY]["saved_run_id"]


# --- empty and error states ------------------------------------------------------------------------


def test_heading_and_description():
    at = _session(HISTORY)
    assert [h.value for h in at.header] == ["Analysis History & Reports"]
    assert any("Revisit saved spatial analyses" in c.value for c in at.main.caption)


def test_empty_history_invents_nothing(storage):
    at = _session(HISTORY)
    assert not at.exception
    assert [i.value for i in at.info] == [
        "No runs saved yet. Run an analysis and use 'Save this run to history' on the Summary page."]
    assert len(at.metric) == 0 and len(at.dataframe) == 0 and len(at.selectbox) == 0
    assert not storage[0].exists()                                       # reading never creates the database


def test_unreadable_history_shows_the_error_and_stops(monkeypatch, tmp_path):
    folder = tmp_path / "a_folder"
    folder.mkdir()
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", folder)
    at = _session(HISTORY)
    assert not at.exception and any("Could not read the run history" in e.value for e in at.error)
    assert len(at.metric) == 0


def test_no_selection_shows_its_own_empty_state():
    at = _saved()
    _go(at, HISTORY)
    assert at.selectbox(key="history_report_run").value is None
    assert any("Choose a saved analysis above" in i.value for i in at.info)
    assert _downloads(at) == []
    assert [s.value for s in at.subheader] == ["Saved analyses", ":material/touch_app: No analysis selected"]


# --- overview and table -------------------------------------------------------------------------------


def test_kpis_come_from_the_saved_records(storage):
    at = _saved()
    at.button(key="generate_reports").click().run()
    _go(at, HISTORY)
    run = list_runs(db_path=storage[0])[0]
    assert _metrics(at) == {"Saved analyses": "1", "Latest analysis (UTC)": run["created_at"][:10],
                            "Analyses with reports": "1", "Report files available": "3"}


def test_kpis_count_only_files_that_still_exist(storage):
    at = _saved()
    at.button(key="generate_reports").click().run()
    (storage[1] / _run_id(at) / "report.pdf").unlink()
    _go(at, HISTORY)
    assert _metrics(at)["Report files available"] == "2"


def test_counts_say_when_the_list_is_cut_off(monkeypatch):
    at = _saved()
    monkeypatch.setattr(dashboard, "HISTORY_LIMIT", 1)
    _go(at, HISTORY)
    assert _metrics(at)["Saved analyses"] == "1+"


def test_table_lists_every_saved_run_with_real_values():
    at = _saved()
    at.number_input(key="p_bandwidth_m").set_value(600.0).run()
    at.button(key="save_run").click().run()
    second = _run_id(at)
    _go(at, HISTORY)
    table = at.dataframe[0].value
    assert len(table) == 2 and table["run id"].iloc[0] == second
    assert table["analysis id"].iloc[0] == second[:8]
    assert table["status"].tolist() == ["complete", "complete"]
    assert table["clusters"].astype(str).tolist() == ["2", "2"]
    assert table["accepted / total rows"].tolist() == ["19 / 19", "19 / 19"]
    assert table["bandwidth_m"].tolist() == [600.0, 300.0]


def test_actions_match_what_can_really_be_done():
    at = _saved()
    _go(at, HISTORY)
    assert at.dataframe[0].value["actions"].tolist() == ["View, generate"]
    earlier = AppTest.from_string(SCRIPT, default_timeout=120)
    earlier.session_state["page"] = HISTORY
    earlier.run()                                                        # a new session cannot generate
    assert earlier.dataframe[0].value["actions"].tolist() == ["View"]
    _go(at, SUMMARY)
    at.button(key="generate_reports").click().run()
    _go(at, HISTORY)
    assert at.dataframe[0].value["actions"].tolist() == ["View, download"]


def test_status_colours_only_mark_status_text():
    assert dashboard._history_cell_colour("complete").endswith(dashboard.SUCCESS)
    assert dashboard._history_cell_colour("unusable dataset (no analysis)").endswith(dashboard.WARNING)
    assert dashboard._history_cell_colour("field_export.csv") == "" and dashboard._history_cell_colour(3) == ""


# --- details --------------------------------------------------------------------------------------------


def test_details_show_what_was_stored():
    at = _saved()
    run_id = _run_id(at)
    _go(at, HISTORY)
    _select(at, run_id)
    assert not at.exception
    assert any(s.value == f"Analysis {run_id[:8]}" for s in at.subheader)
    metrics = _metrics(at)
    assert (metrics["Rows in file"], metrics["Accepted"], metrics["Rejected"]) == ("19", "19", "0")
    assert (metrics["Clusters"], metrics["Candidate hotspots"], metrics["Noise incidents"]) == ("2", "1", "1")
    text = _text(at)
    assert f"Run ID {run_id}" in text and HISTORY_STORAGE_NOTE in text
    for fact in ("Eps: 250 m", "Min samples: 5", "at least 10 incidents", "Bandwidth: 300 m", "Kernel: gaussian",
                 "Grid cell: 100 m", "High-density quantile: 0.95"):
        assert fact in text


def test_details_use_the_saved_parameters_not_the_current_ones():
    at = _saved()
    run_id = _run_id(at)
    at.number_input(key="p_bandwidth_m").set_value(600.0).run()          # current setting differs from the saved one
    _go(at, HISTORY)
    _select(at, run_id)
    assert "Bandwidth: 300 m" in _text(at)


def test_details_escape_the_file_name():
    at = _saved("a_b*c.csv")
    run_id = _run_id(at)
    _go(at, HISTORY)
    _select(at, run_id)
    assert "a\\_b\\*c\\.csv" in _text(at)


def test_synthetic_runs_stay_labelled():
    at = _saved("synthetic_demo.csv")
    run_id = _run_id(at)
    _go(at, HISTORY)
    _select(at, run_id)
    assert SYNTHETIC_NOTICE in [i.value for i in at.info]


# --- reports -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("registered, exists, can_generate, expected", [
    (None, [], False, "Not generated"),
    (None, [], True, "Ready to generate"),
    (["a", "b"], [True, True], False, "Available"),
    (["a", "b"], [True, False], False, "Partly available"),
    (["a", "b"], [False, False], False, "Files missing"),
    (["a", "b"], [True], False, "Partly available"),                     # one stored path was invalid
])
def test_report_status_comes_from_real_state(registered, exists, can_generate, expected, tmp_path):
    files = []
    for index, present in enumerate(exists):
        path = tmp_path / f"f{index}"
        if present:
            path.write_text("x", encoding="utf-8")
        files.append(path)
    assert report_status({"report_paths": registered}, files, can_generate) == expected


def test_downloads_for_a_run_with_reports():
    at = _saved()
    at.button(key="generate_reports").click().run()
    run_id = _run_id(at)
    _go(at, HISTORY)
    _select(at, run_id)
    assert _downloads(at) == ["Download incidents.csv", "Download clusters.csv", "Download report.pdf"]
    assert CSV_SAFETY_WARNING in [w.value for w in at.warning]
    assert any("-badge[Available]" in m.value for m in at.main.markdown)
    assert "history_generate_reports" not in _keys(at)


def test_generate_from_history_uses_the_saved_session_run(storage):
    at = _saved()
    run_id = _run_id(at)
    _go(at, HISTORY)
    _select(at, run_id)
    assert any("-badge[Ready to generate]" in m.value for m in at.main.markdown)
    at.button(key="history_generate_reports").click().run()
    assert not at.exception
    assert "history_generate_reports" not in _keys(at)
    assert any("Reports generated for this run." == s.value for s in at.success)
    assert len(_downloads(at)) == 3 and _metrics(at)["Report files available"] == "3"
    assert at.dataframe[0].value["reports"].tolist() == ["3 file(s)"]
    assert get_run(run_id, storage[0])["report_paths"] == [f"{run_id}/incidents.csv", f"{run_id}/clusters.csv",
                                                           f"{run_id}/report.pdf"]
    at.run()
    assert not any("Reports generated" in s.value for s in at.success)   # the notice is shown once
    _go(at, SUMMARY)
    assert len(_downloads(at)) == 3 and "generate_reports" not in _keys(at)


def test_generate_failure_on_history_is_clear_and_can_be_retried(monkeypatch, tmp_path, storage):
    at = _saved()
    run_id = _run_id(at)
    blocker = tmp_path / "a_file_not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", blocker)
    _go(at, HISTORY)
    _select(at, run_id)
    at.button(key="history_generate_reports").click().run()
    assert not at.exception
    assert any("Could not generate reports" in e.value for e in at.error)
    assert "No reports were saved for this attempt" in _text(at)
    assert not any(s.value.startswith("Reports generated") for s in at.success)
    assert any("-badge[Ready to generate]" in m.value for m in at.main.markdown)   # no fake completed state
    assert get_run(run_id, storage[0])["report_paths"] is None
    assert "history_generate_reports" in _keys(at) and _downloads(at) == []
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", storage[1])
    at.button(key="history_generate_reports").click().run()
    assert len(_downloads(at)) == 3


def test_run_from_an_earlier_session_cannot_generate_and_says_why():
    at = _saved()
    run_id = _run_id(at)
    later = AppTest.from_string(SCRIPT, default_timeout=120)
    later.session_state["page"] = HISTORY
    later.run()
    _select(later, run_id)
    assert not later.exception
    assert any("-badge[Not generated]" in m.value for m in later.main.markdown)
    assert any("No reports registered yet" in i.value for i in later.info)
    assert "cannot be regenerated" in _text(later)
    assert "history_generate_reports" not in _keys(later) and _downloads(later) == []


def test_missing_files_are_reported_not_hidden(storage):
    at = _saved()
    at.button(key="generate_reports").click().run()
    run_id = _run_id(at)
    for path in (storage[1] / run_id).iterdir():
        path.unlink()
    _go(at, HISTORY)
    _select(at, run_id)
    assert any("-badge[Files missing]" in m.value for m in at.main.markdown)
    assert sum("Missing file:" in w.value for w in at.warning) == 3 and _downloads(at) == []


def test_invalid_stored_path_is_reported(monkeypatch):
    at = _saved()
    at.button(key="generate_reports").click().run()
    run_id = _run_id(at)
    real = dashboard.list_runs

    def tampered(*args, **kwargs):
        runs = real(*args, **kwargs)
        runs[0]["report_paths"] = runs[0]["report_paths"][:2] + ["../outside.pdf"]
        return runs

    monkeypatch.setattr(dashboard, "list_runs", tampered)
    _go(at, HISTORY)
    _select(at, run_id)
    assert any("Invalid stored report path" in e.value for e in at.error)
    assert any("-badge[Partly available]" in m.value for m in at.main.markdown)
    assert _downloads(at) == ["Download incidents.csv", "Download clusters.csv"]


# --- buttons do not stay on screen after they have finished -------------------------------------------


def test_save_button_goes_in_the_same_run():
    at = _session()
    at.button(key="save_run").click().run()
    assert "save_run" not in _keys(at) and "generate_reports" in _keys(at)


def test_generate_button_goes_in_the_same_run():
    at = _saved()
    at.button(key="generate_reports").click().run()
    assert "generate_reports" not in _keys(at) and len(_downloads(at)) == 3
    assert dashboard.REPORT_FILES_NOTE not in _text(at)                  # it described a step now finished


def test_save_button_stays_when_saving_fails(monkeypatch):
    def failing(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(dashboard, "record_run", failing)
    at = _session()
    at.button(key="save_run").click().run()
    assert any("Could not save the run" in e.value for e in at.error) and "save_run" in _keys(at)
