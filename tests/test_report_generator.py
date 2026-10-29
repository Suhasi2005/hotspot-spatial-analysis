"""CSV and PDF report tests. Synthetic data, temporary folders only."""

import copy
import csv
import io
from dataclasses import asdict, replace

import pandas as pd
import pytest
from reportlab.platypus import Paragraph

from config.settings import AnalysisConfig, DBSCANParams
from modules.app_controller import run_analysis
from modules.contracts import AnalysisError
from modules.data_manager import load_raw_dataset
from modules.data_validator import validate_and_clean
from modules.report_generator import (
    CLUSTERS_FILE,
    CSV_SAFETY_WARNING,
    INCIDENTS_FILE,
    PDF_FILE,
    PDF_MAX_CLUSTERS,
    _csv_value,
    _story,
    export_csv,
    export_pdf,
    pdf_markup,
    report_sections,
)

TRICKY = "<b>x</b> & ≥ 日本"           # markup, >=, and Japanese text
ROWS = (
    ["incident_id,latitude,longitude,severity,incident_date,note"]
    + [f"A{i},{23.0200 + 0.0001 * i:.4f},72.5700,major,2024-01-0{1 + i % 9},=1+1" for i in range(12)]
    + [f"B{i},{23.0650 + 0.0001 * i:.4f},72.5800,,2024-02-1{i},\"{TRICKY}\"" for i in range(6)]
    + ["BAD,not-a-number,72.57,minor,,x"]                                 # rejected -> source-row gap
    + ["N0,23.1000,72.6500,minor,,plain"]
)


def _run(rows=ROWS, name="synthetic_reports.csv", config=None):
    upload = io.BytesIO("\n".join(rows).encode("utf-8"))
    upload.name = name
    return run_analysis(upload, config or AnalysisConfig(), persist=False)


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


# --- CSV ---------------------------------------------------------------------------------


def test_incidents_csv_content_order_and_metadata(tmp_path):
    run = _run()
    incidents, clusters = export_csv(run, tmp_path)
    assert [incidents.name, clusters.name] == [INCIDENTS_FILE, CLUSTERS_FILE]
    assert incidents.read_bytes()[:3] == b"\xef\xbb\xbf"                  # UTF-8 BOM
    assert b"\r\n" in incidents.read_bytes()                              # csv-module CRLF line endings
    header, *rows = _read_csv(incidents)
    frame = run.clusters.labeled_frame
    assert header == ["source_row", *frame.columns, "is_noise", "cluster_is_candidate_hotspot"]
    assert len(rows) == len(frame) == 19
    assert [int(r[0]) for r in rows] == list(frame.index)                 # source rows kept (gap at 18)
    assert 18 not in [int(r[0]) for r in rows]
    by_name = [dict(zip(header, r)) for r in rows]
    assert [r["incident_id"] for r in by_name] == frame["incident_id"].tolist()   # file order
    candidates = {c.cluster_label: c.is_candidate_hotspot for c in run.clusters.clusters}
    for record, label in zip(by_name, frame["cluster_label"]):
        assert int(record["cluster_label"]) == label
        assert record["is_noise"] == ("true" if label == -1 else "false")
        assert record["cluster_is_candidate_hotspot"] == ("true" if candidates.get(label, False) else "false")


def test_incidents_csv_preserves_values_exactly(tmp_path):
    run = _run()
    incidents, _ = export_csv(run, tmp_path)
    header, *rows = _read_csv(incidents)
    records = [dict(zip(header, r)) for r in rows]
    frame = run.clusters.labeled_frame
    assert [float(r["latitude"]) for r in records] == frame["latitude"].tolist()   # exact round trip
    assert [float(r["longitude"]) for r in records] == frame["longitude"].tolist()
    assert records[0]["note"] == "=1+1"                                   # canonical text, no apostrophe
    assert records[12]["note"] == TRICKY                                  # markup + non-Latin unchanged
    assert records[0]["severity"] == "major" and records[12]["severity"] == ""     # missing -> empty
    assert records[0]["incident_date"] == "2024-01-01"                    # ISO date
    assert records[-1]["incident_date"] == ""                             # missing date -> empty


def test_clusters_csv_has_every_cluster_and_overlap(tmp_path):
    run = _run()
    _, clusters_path = export_csv(run, tmp_path)
    header, *rows = _read_csv(clusters_path)
    assert header[:6] == ["cluster_label", "incident_count", "centroid_lat", "centroid_lon", "radius_m",
                          "is_candidate_hotspot"]
    assert [int(r[0]) for r in rows] == [c.cluster_label for c in run.clusters.clusters]
    overlap = {o.cluster_label: o for o in run.summary.method_comparison.per_cluster}
    for row, c in zip(rows, run.clusters.clusters):
        record = dict(zip(header, row))
        assert float(record["centroid_lat"]) == c.centroid_lat and float(record["radius_m"]) == c.radius_m
        assert int(record["incident_count"]) == c.incident_count
        assert int(record["members_at_high_density"]) == overlap[c.cluster_label].members_at_high_density


def test_csv_reloads_with_the_project_loader(tmp_path):
    run = _run()
    incidents, _ = export_csv(run, tmp_path)
    raw, _ = load_raw_dataset(incidents)
    again = validate_and_clean(raw, "reloaded.csv")
    assert again.report.rejected_rows == 0
    assert again.frame["incident_id"].tolist() == run.dataset.frame["incident_id"].tolist()
    assert again.frame["latitude"].tolist() == run.dataset.frame["latitude"].tolist()


@pytest.mark.parametrize("value,expected", [
    (None, ""), (float("nan"), ""), (pd.NaT, ""), (True, "true"), (False, "false"), (7, "7"),
    (0.1 + 0.2, "0.30000000000000004"), (pd.Timestamp("2024-03-05"), "2024-03-05"),
    (pd.Timestamp("2024-03-05 14:30"), "2024-03-05T14:30:00"), ("=SUM(A1)", "=SUM(A1)"),
])
def test_csv_value_conversion(value, expected):
    assert _csv_value(value) == expected


def test_many_clusters_all_in_csv_and_pdf_truncation_note(tmp_path):
    points = [f"C{i}{k},{10 + i * 0.05:.4f},{20 + k * 0.0001:.4f}" for i in range(60) for k in range(2)]
    run = _run(["incident_id,latitude,longitude", *points], config=AnalysisConfig(dbscan=DBSCANParams(250, 2)))
    assert len(run.clusters.clusters) == 60
    _, clusters_path = export_csv(run, tmp_path)
    assert len(_read_csv(clusters_path)) == 61
    section = next(s for s in report_sections(run) if s.heading == "DBSCAN clusters")
    assert len(section.tables[0]) == PDF_MAX_CLUSTERS + 1                 # header + 50
    assert [int(r[0]) for r in section.tables[0][1:]] == list(range(50))  # ascending label order
    assert any("first 50 of 60" in p and "clusters.csv contains all clusters" in p for p in section.paragraphs)


def test_column_name_clash_is_refused_without_files(tmp_path):
    rows = ["incident_id,latitude,longitude,is_noise"] + [f"A{i},{23.02 + 0.0001 * i:.4f},72.57,x" for i in range(6)]
    with pytest.raises(AnalysisError, match="is_noise"):
        export_csv(_run(rows), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_existing_files_are_never_overwritten(tmp_path):
    run = _run()
    (tmp_path / CLUSTERS_FILE).write_text("keep me", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_csv(run, tmp_path)
    assert (tmp_path / CLUSTERS_FILE).read_text(encoding="utf-8") == "keep me"     # pre-existing intact
    assert not (tmp_path / INCIDENTS_FILE).exists()                       # own partial file removed
    (tmp_path / PDF_FILE).write_bytes(b"old")
    with pytest.raises(FileExistsError):
        export_pdf(run, tmp_path)
    assert (tmp_path / PDF_FILE).read_bytes() == b"old"


@pytest.mark.parametrize("case", ["unusable", "no-density", "no-summary"])
def test_ineligible_runs_are_refused(tmp_path, case):
    if case == "unusable":
        run = _run(["incident_id,latitude,longitude", ",1,2"])
    else:
        base = _run()
        run = replace(base, density=None) if case == "no-density" else replace(base, summary=None)
    for export in (export_csv, export_pdf):
        with pytest.raises(AnalysisError):
            export(run, tmp_path)
    assert list(tmp_path.iterdir()) == []


# --- PDF ------------------------------------------------------------------------------------


def test_pdf_sections_in_documented_order():
    headings = [s.heading for s in report_sections(_run())]
    assert headings == ["Run", "Data quality", "Parameters", "DBSCAN clusters", "KDE density",
                        "DBSCAN vs KDE (descriptive comparison)", "Incidents by category", "Limitations and notes"]


def test_pdf_run_quality_and_parameters_content():
    run = _run()
    sections = {s.heading: s for s in report_sections(run)}
    assert sections["Run"].paragraphs == (f"Run ID: {run.run_id}", f"Saved (UTC): {run.created_at.isoformat()}",
                                          "Source file: synthetic_reports.csv")
    assert "Rows in file: 20; accepted: 19; rejected: 1." in sections["Data quality"].paragraphs
    issue_codes = [row[1] for row in sections["Data quality"].tables[0][1:]]
    assert "NON_NUMERIC_COORDINATE" in issue_codes
    parameters = dict(sections["Parameters"].tables[0][1:])

    def flat(d, prefix=""):
        for k, v in d.items():
            yield from flat(v, f"{prefix}{k}.") if isinstance(v, dict) else [(f"{prefix}{k}", v)]
    expected = dict(flat(asdict(run.config)))
    assert set(parameters) == set(expected)                               # every AnalysisConfig parameter
    assert parameters["dbscan.eps_m"] == "250.0" and parameters["study_area"] == "none"


def test_pdf_kde_and_comparison_content():
    run = _run()
    sections = {s.heading: s for s in report_sections(run)}
    kde = dict(sections["KDE density"].tables[0][1:])
    assert kde["grid size (rows x columns)"] == f"{run.density.density.shape[0]} x {run.density.density.shape[1]}"
    assert kde["density units"] == run.density.params["density_units"]
    assert "grid extent (south, north, west, east)" in kde and "high_density_threshold (relative score)" in kde
    table = sections["DBSCAN vs KDE (descriptive comparison)"].tables[0]
    mc = run.summary.method_comparison
    assert table[3] == ("Total (eligible)", str(mc.high_density_eligible), str(mc.not_high_density_eligible),
                        str(mc.eligible_count))
    categories = sections["Incidents by category"].tables
    assert categories[0][0] == ("severity", "Incidents")


def test_pdf_limitations_cover_open_items_and_warnings():
    run = _run()
    text = " ".join(next(s for s in report_sections(run) if s.heading == "Limitations and notes").paragraphs)
    for phrase in ("density-threshold method", "mixed time zones", "dataset identity", "fixed algorithm constants",
                   "size rule only", "relative density scores", CSV_SAFETY_WARNING, "formula"):
        assert phrase in text
    for note in run.summary.notes + run.summary.method_comparison.notes:
        assert note in text
    for sentence in text.split(". "):
        if "significan" in sentence:
            assert "not" in sentence or "no significance" in sentence or "None of" in sentence


def test_pdf_markup_escaping_and_unsupported_characters():
    assert pdf_markup(TRICKY) == "&lt;b&gt;x&lt;/b&gt; &amp; &gt;= [U+65E5][U+672C]"
    assert pdf_markup("ok — km²") == "ok — km²"                  # in the font's character set
    assert pdf_markup("a\x00b\nc") == "a[U+0000]b c"
    run = _run(name=f"{TRICKY}.csv")
    story = _story(report_sections(run), 450)
    texts = [f.text for f in story if isinstance(f, Paragraph)]
    assert any("Source file: &lt;b&gt;x&lt;/b&gt; &amp; &gt;= [U+65E5][U+672C].csv" == t for t in texts)
    assert not any("<b>x</b>" in t for t in texts)


def test_pdf_file_integrity_and_determinism(tmp_path):
    run = _run(name=f"{TRICKY}.csv")                                      # builds despite markup in values
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = export_pdf(run, tmp_path / "a")
    second = export_pdf(run, tmp_path / "b")
    data = first.read_bytes()
    assert first.name == PDF_FILE and data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
    assert data == second.read_bytes()                                    # deterministic


def test_exports_do_not_mutate_the_run(tmp_path):
    run = _run()
    before = (run.dataset.frame.copy(deep=True), run.clusters.labeled_frame.copy(deep=True),
              copy.deepcopy(run.clusters.clusters), copy.deepcopy(run.summary), run.density.density.copy())
    export_csv(run, tmp_path)
    export_pdf(run, tmp_path)
    pd.testing.assert_frame_equal(run.dataset.frame, before[0])
    pd.testing.assert_frame_equal(run.clusters.labeled_frame, before[1])
    assert run.clusters.clusters == before[2] and run.summary == before[3]
    assert (run.density.density == before[4]).all()
