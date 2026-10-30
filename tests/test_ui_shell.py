"""Application-shell tests (Stage 10B Phase 2): headers, sidebar status, KPI strip, navigation.

Synthetic data and temporary history/reports locations only.
"""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from modules.contracts import AnalysisError
from modules.dashboard import (
    BRAND_NAME,
    BRAND_TAGLINE,
    CACHE_KEY,
    KPI_PER_ROW,
    NOT_RUN,
    PAGE_INFO,
    PAGES,
    analysis_status,
    escape_markdown,
    kpi_rows,
)
from modules.data_validator import validate_and_clean

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page(PAGE)\n"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")


def _dataset(name="synthetic_shell.csv", usable=True):
    if not usable:
        return validate_and_clean(pd.DataFrame({"incident_id": [""], "latitude": ["1"], "longitude": ["2"]}, dtype=str), name)
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(len(points))],
                        "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]}, dtype=str)
    return validate_and_clean(raw, name)


def _app(page, dataset=None):
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr(page)), default_timeout=120)
    if dataset is not None:
        at.session_state["dataset"] = dataset
    return at.run()


def _sidebar_captions(at):
    return [c.value for c in at.sidebar.caption]


def _metrics(at):
    return {m.label: m.value for m in at.metric}


# --- pure helpers ------------------------------------------------------------------------------


def test_kpi_rows_never_exceed_four_per_row():
    items = [(f"k{i}", str(i)) for i in range(9)]
    rows = kpi_rows(items)
    assert KPI_PER_ROW == 4 and [len(r) for r in rows] == [4, 4, 1]
    assert [item for row in rows for item in row] == items                  # order preserved
    assert kpi_rows([]) == []


@pytest.mark.parametrize("entry,expected", [
    (None, NOT_RUN),
    ({"cluster_error": None, "density_error": None, "summary_error": None}, "Complete"),
    ({"cluster_error": "x", "density_error": None, "summary_error": None}, "Partial — DBSCAN failed"),
    ({"cluster_error": None, "density_error": "x", "summary_error": None}, "Partial — KDE failed"),
    ({"cluster_error": None, "density_error": None, "summary_error": "x"}, "Partial — summary failed"),
    ({"cluster_error": "x", "density_error": "y", "summary_error": None}, "Failed"),
])
def test_analysis_status(entry, expected):
    assert analysis_status(entry) == expected


def test_escape_markdown_neutralises_formatting_and_latex():
    raw = "*bold* _it_ [x](y) $x$ <b>#1</b> a|b `c` \\"
    escaped = escape_markdown(raw)
    assert all(f"\\{ch}" in escaped for ch in "*_[]()$<>#|`")
    assert escape_markdown("plain name 2024") == "plain name 2024"


def test_page_info_covers_every_page_with_icons_and_descriptions():
    assert set(PAGE_INFO) == set(PAGES)
    assert [PAGE_INFO[p][0] for p in PAGES] == ["Data", "Clusters", "Density", "Summary", "History & Reports"]
    assert all(PAGE_INFO[p][1].startswith(":material/") for p in PAGES)
    assert len({PAGE_INFO[p][2] for p in PAGES}) == len(PAGES)              # unique URL paths
    assert PAGE_INFO["Data"][3] == "Import and validate incident datasets."
    assert PAGE_INFO["Density (KDE)"][3] == "Explore relative spatial density using KDE."
    assert (BRAND_NAME, BRAND_TAGLINE) == ("Hotspot Analytics", "Spatial Incident Analysis")


# --- headers ------------------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_every_page_has_title_and_description(page):
    at = _app(page, _dataset() if page != "Data" else None)
    assert not at.exception
    assert [h.value for h in at.header] == [page]                            # title text unchanged
    assert PAGE_INFO[page][3] in [c.value for c in at.main.caption]


# --- sidebar dataset status ----------------------------------------------------------------------


def test_status_without_dataset():
    at = _app("Data")
    assert "No dataset loaded." in _sidebar_captions(at)


def test_status_reflects_real_dataset_and_analysis():
    at = _app("Summary", _dataset())
    status = next(c for c in _sidebar_captions(at) if "Rows" in c)
    assert "synthetic\\_shell\\.csv" in status                              # file name, escaped
    assert "Rows 19 · Accepted 19 · Rejected 0" in status
    assert "Analysis: Complete" in status and "Saved run" not in status
    at.button(key="save_run").click().run()
    run_id = at.session_state[CACHE_KEY]["saved_run_id"]
    status = next(c for c in _sidebar_captions(at) if "Rows" in c)
    assert f"Saved run: {run_id[:8]}" in status


def test_status_before_any_analysis_and_for_unusable_data():
    data_page = _app("History & Reports", _dataset())                       # no analysis has run yet
    assert any("Analysis: Not run" in c for c in _sidebar_captions(data_page))
    unusable = _app("Summary", _dataset(usable=False))
    assert any("Analysis: Dataset unusable" in c for c in _sidebar_captions(unusable))


def test_status_shows_partial_failure():
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr("Summary")), default_timeout=120)
    at.session_state["dataset"] = _dataset()
    at.run()
    at.number_input(key="p_grid_cell_m").set_value(1.0).run()               # KDE refuses the grid
    assert any("Analysis: Partial — KDE failed" in c for c in _sidebar_captions(at))
    assert _metrics(at)["Analysis status"] == "Partial — KDE failed"


def test_markdown_in_file_names_is_not_rendered():
    at = _app("Summary", _dataset(name="*evil* $x$ [link](http://x).csv"))
    status = next(c for c in _sidebar_captions(at) if "Rows" in c)
    assert "\\*evil\\* \\$x\\$ \\[link\\]\\(http://x\\)\\.csv" in status


# --- KPI strip --------------------------------------------------------------------------------------


def test_summary_kpis_use_existing_values():
    at = _app("Summary", _dataset())
    m = _metrics(at)
    assert (m["Rows in file"], m["Accepted incidents"], m["Rejected"], m["Analysis status"]) == ("19", "19", "0", "Complete")
    assert (m["Clusters"], m["Candidate hotspots"], m["Noise incidents"], m["Noise share"]) == ("2", "1", "1 of 19", "5.3%")
    assert len(at.metric) == 8


def test_kpis_show_not_run_when_dbscan_did_not_produce_results(monkeypatch):
    def failing(*args, **kwargs):
        raise AnalysisError("simulated DBSCAN failure")
    monkeypatch.setattr(dashboard, "cluster_dataset", failing)
    at = _app("Summary", _dataset())
    m = _metrics(at)
    assert (m["Clusters"], m["Candidate hotspots"], m["Noise incidents"], m["Noise share"]) == (NOT_RUN,) * 4
    assert m["Analysis status"] == "Partial — DBSCAN failed"


def test_clusters_and_density_kpis():
    clusters = _metrics(_app("Clusters (DBSCAN)", _dataset()))
    assert clusters == {"Clusters": "2", "Candidate hotspots": "1", "Noise incidents": "1 of 19",
                        "Analysis status": "Complete"}
    density = _metrics(_app("Density (KDE)", _dataset()))
    assert density["Incidents used"] == "19" and density["Bandwidth"] == "300 m"
    assert " × " in density["Grid cells"] and density["Analysis status"] == "Complete"


# --- sidebar structure -------------------------------------------------------------------------------


def test_parameters_are_collapsible_and_filters_only_on_clusters():
    clusters = _app("Clusters (DBSCAN)", _dataset())
    labels = [e.label for e in clusters.sidebar.expander]
    assert labels == ["Analysis parameters", "Display filters (display only)"]
    for page in ("Density (KDE)", "Summary"):
        assert [e.label for e in _app(page, _dataset()).sidebar.expander] == ["Analysis parameters"]
    assert [e.label for e in _app("Data").sidebar.expander] == []


# --- real app.py navigation -----------------------------------------------------------------------------


def test_shell_css_is_static_and_uses_the_accent():
    from modules.ui_theme import ACCENT, NAV_ACTIVE_KEY, SHELL_CSS, SURFACE

    assert f".st-key-{NAV_ACTIVE_KEY} a" in SHELL_CSS and ACCENT in SHELL_CSS and SURFACE in SHELL_CSS
    assert "{" in SHELL_CSS and "<" not in SHELL_CSS and "script" not in SHELL_CSS.lower()


def test_app_navigation_renders_brand_and_links():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert any(BRAND_NAME in m.value for m in at.sidebar.markdown)
    assert BRAND_TAGLINE in _sidebar_captions(at)
    assert [h.value for h in at.header] == ["Data"]                          # default page
