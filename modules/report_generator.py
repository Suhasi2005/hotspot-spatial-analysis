"""CSV and PDF exports. Owner: Member 5 (Reporting).

Reports must state the method limitations: clusters and density surfaces are
descriptive; candidate hotspots are not statistically significant hotspots.

export_csv / export_pdf write into an existing folder and never overwrite a
file (exclusive creation). They only read the AnalysisRun. The controller's
generate_reports decides the folder, validates, moves and registers files.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config.settings import REPORTS_DIR
from modules.contracts import NOISE_LABEL, AnalysisError, AnalysisRun
from modules.data_validator import summarize_quality

INCIDENTS_FILE = "incidents.csv"
CLUSTERS_FILE = "clusters.csv"
PDF_FILE = "report.pdf"
CSV_ENCODING = "utf-8-sig"            # UTF-8 with BOM, so spreadsheet software detects the encoding
PDF_MAX_CLUSTERS = 50
ADDED_INCIDENT_COLUMNS = ("source_row", "is_noise", "cluster_is_candidate_hotspot")
CLUSTER_COLUMNS = (
    "cluster_label", "incident_count", "centroid_lat", "centroid_lon", "radius_m", "is_candidate_hotspot",
    "eligible_members", "outside_grid_members", "members_at_high_density", "high_density_share",
)
PDF_ENCODING = "cp1252"               # the built-in Helvetica font covers Windows-1252 only

CSV_SAFETY_WARNING = (
    "Spreadsheet safety: the CSV files keep the original text exactly as it was in the input. Opening a CSV "
    "that contains untrusted text in spreadsheet software (Excel, LibreOffice, Google Sheets) may execute "
    "cells beginning with =, +, - or @ as formulas. Open such files as plain text or import them with "
    "formula evaluation disabled."
)
LIMITATIONS: tuple[str, ...] = (
    "Descriptive results only: DBSCAN clusters, KDE density and the method comparison do not establish "
    "statistical significance, and no significance test was run.",
    "Candidate hotspots follow the configured size rule only (min_incidents); they are not statistically "
    "significant hotspots.",
    "KDE values are relative density scores, not incident counts or incidents per km2, and they are not "
    "adjusted for exposure such as traffic, population or time.",
    "Open item - density-threshold method: the high-density threshold is a quantile of all grid cells, "
    "including empty padding around the data, so it can be low enough that isolated incidents count as "
    "high density. Treat 'high density' as relative to this grid only.",
    "Open item - mixed time zones: when incident dates carry different UTC offsets, date validation leaves "
    "them as text-like values (date counts convert them to UTC); such dates are not normalised in the "
    "incident data.",
    "Open item - dataset identity: the run history identifies the input only by its file name, so different "
    "files with the same name cannot be told apart.",
    "Open item - fixed algorithm constants: results also depend on code constants that are not part of the "
    "saved configuration (for example the 3-bandwidth KDE grid padding and the grid-size cap), so the saved "
    "parameters alone do not reproduce results if those constants change.",
    CSV_SAFETY_WARNING,
)


@dataclass(frozen=True)
class ReportSection:
    """Plain (unescaped) report content; the PDF builder escapes it."""

    heading: str
    paragraphs: tuple[str, ...] = ()
    tables: tuple[tuple[tuple[str, ...], ...], ...] = ()   # each table: header row first


# --- CSV ----------------------------------------------------------------------------


def export_csv(run: AnalysisRun, out_dir: Path = REPORTS_DIR) -> list[Path]:
    """Write incidents.csv and clusters.csv into the existing folder `out_dir`.

    incidents.csv: one row per accepted incident in file order — source_row
    (the cleaned frame's index), every column of the clustered frame in order
    (required, optional and extra columns unchanged, then cluster_label),
    is_noise and cluster_is_candidate_hotspot. clusters.csv: every cluster in
    label order with its summary and Stage 6 overlap counts.

    Values: floats at full round-trip precision, booleans "true"/"false",
    dates ISO 8601, missing values as empty cells. Text is written exactly as
    stored (see CSV_SAFETY_WARNING). UTF-8 with BOM, csv-module quoting, CRLF
    line endings. Never overwrites: an existing file raises FileExistsError;
    if the second file fails, the first file written by this call is removed.
    Raises AnalysisError for an ineligible run or a column-name clash.
    """
    _require_complete(run)
    out_dir = Path(out_dir)
    frame = run.clusters.labeled_frame
    clash = [c for c in ADDED_INCIDENT_COLUMNS if c in frame.columns]
    if clash:
        raise AnalysisError(f"Cannot export: the data already has column(s) named {clash}.")
    candidates = {c.cluster_label: c.is_candidate_hotspot for c in run.clusters.clusters}
    labels = frame["cluster_label"].to_numpy()

    incident_rows = [list(ADDED_INCIDENT_COLUMNS[:1]) + list(frame.columns) + list(ADDED_INCIDENT_COLUMNS[1:])]
    columns = [frame[c].tolist() for c in frame.columns]      # tolist keeps pd.Timestamp / NaT
    for pos in range(len(frame)):
        label = int(labels[pos])
        incident_rows.append(
            [_csv_value(frame.index[pos])]
            + [_csv_value(values[pos]) for values in columns]
            + [_csv_value(label == NOISE_LABEL), _csv_value(candidates.get(label, False))]
        )

    overlap = {o.cluster_label: o for o in run.summary.method_comparison.per_cluster}
    cluster_rows = [list(CLUSTER_COLUMNS)]
    for c in run.clusters.clusters:
        o = overlap.get(c.cluster_label)
        cluster_rows.append([_csv_value(v) for v in (
            c.cluster_label, c.incident_count, c.centroid_lat, c.centroid_lon, c.radius_m, c.is_candidate_hotspot,
            None if o is None else o.eligible_members, None if o is None else o.outside_grid_members,
            None if o is None else o.members_at_high_density, None if o is None else o.high_density_share,
        )])

    written: list[Path] = []
    try:
        for name, rows in ((INCIDENTS_FILE, incident_rows), (CLUSTERS_FILE, cluster_rows)):
            path = out_dir / name
            with open(path, "x", encoding=CSV_ENCODING, newline="") as handle:
                written.append(path)
                csv.writer(handle).writerows(rows)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return written


def _csv_value(value: Any) -> str:
    if value is None or value is pd.NaT:
        return ""
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return "" if math.isnan(value) else repr(float(value))
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if value == value.normalize() else value.isoformat()
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value)


# --- PDF ------------------------------------------------------------------------------


def export_pdf(run: AnalysisRun, out_dir: Path = REPORTS_DIR) -> Path:
    """Write report.pdf into the existing folder `out_dir` (ReportLab, A4).

    Content comes from report_sections(run). Every value is mapped to the
    Helvetica character set (unsupported characters become a visible
    "[U+XXXX]") and XML-escaped before it reaches ReportLab markup. Built in
    ReportLab's invariant mode, so the same run gives identical bytes. Never
    overwrites (FileExistsError). Raises AnalysisError for an ineligible run.
    """
    sections = report_sections(run)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, invariant=1,
                            title=_pdf_plain(f"Hotspot analysis report {run.run_id}"),
                            author="Hotspot Identification and Spatial Analysis")
    doc.build(_story(sections, doc.width))
    path = Path(out_dir) / PDF_FILE
    with open(path, "xb") as handle:
        handle.write(buffer.getvalue())
    return path


def report_sections(run: AnalysisRun) -> list[ReportSection]:
    """The PDF content as plain text: eight sections in the documented order."""
    _require_complete(run)
    report, summary, clusters, density = run.dataset.report, run.summary, run.clusters, run.density
    mc = summary.method_comparison
    sections = [
        ReportSection("Run", (
            f"Run ID: {run.run_id}",
            f"Saved (UTC): {run.created_at.isoformat()}",
            f"Source file: {run.dataset.source_name}",
        )),
    ]

    issues = summarize_quality(report)
    quality_tables = ()
    if not issues.empty:
        header = ("Severity", "Code", "Rows affected", "Row numbers", "Message")
        quality_tables = ((header,) + tuple(
            (str(r.severity), str(r.code), str(r.affected_rows), str(r.rows), str(r.message))
            for r in issues.itertuples(index=False)),)
    sections.append(ReportSection("Data quality", (
        f"Rows in file: {report.total_rows}; accepted: {report.valid_rows}; rejected: {report.rejected_rows}.",
        "No validation issues." if issues.empty else "Validation issues (row numbers are 0-based data rows):",
    ), quality_tables))

    sections.append(ReportSection("Parameters", (
        "Every AnalysisConfig parameter used for this run:",
    ), ((("Parameter", "Value"),) + tuple(_flatten_config(asdict(run.config))),)))

    shown = clusters.clusters[:PDF_MAX_CLUSTERS]
    cluster_note = (
        f"All {len(clusters.clusters)} clusters are shown." if len(clusters.clusters) <= PDF_MAX_CLUSTERS else
        f"Showing the first {PDF_MAX_CLUSTERS} of {len(clusters.clusters)} clusters (ascending label)."
    ) + f" {CLUSTERS_FILE} contains all clusters."
    cluster_table = ((("Cluster", "Incidents", "Centroid lat", "Centroid lon", "Radius (m)", "Candidate (size rule)"),)
                     + tuple((str(c.cluster_label), str(c.incident_count), f"{c.centroid_lat:.6f}",
                              f"{c.centroid_lon:.6f}", f"{c.radius_m:.1f}", "yes" if c.is_candidate_hotspot else "no")
                             for c in shown)) if shown else ()
    sections.append(ReportSection("DBSCAN clusters", (
        f"Clusters: {summary.cluster_count}; candidate hotspots (size rule): {summary.candidate_hotspot_count}; "
        f"noise incidents: {clusters.noise_count} ({summary.noise_share:.1%} of accepted incidents).",
        cluster_note if shown else f"DBSCAN found no clusters; every incident is noise. {CLUSTERS_FILE} has a header only.",
    ), (cluster_table,) if shown else ()))

    p = density.params
    ext = p["grid_extent"]
    sections.append(ReportSection("KDE density", (), ((
        ("Item", "Value"),
        ("bandwidth_m", str(p["bandwidth_m"])), ("kernel", str(p["kernel"])), ("grid_cell_m", str(p["grid_cell_m"])),
        ("grid size (rows x columns)", f"{density.density.shape[0]} x {density.density.shape[1]}"),
        ("grid extent (south, north, west, east)",
         f"{ext['south']:.6f}, {ext['north']:.6f}, {ext['west']:.6f}, {ext['east']:.6f}"),
        ("grid source", str(p["grid_source"])),
        ("high_density_quantile", str(p["high_density_quantile"])),
        ("high_density_threshold (relative score)", f"{density.high_density_threshold:.6g}"),
        ("incidents used", str(p["n_points"])),
        ("density units", str(p["density_units"])),
    ),)))

    sections.append(ReportSection("DBSCAN vs KDE (descriptive comparison)", (
        f"Eligible incidents (inside the KDE grid extent): {mc.eligible_count} of {mc.total_incidents}; "
        f"outside the grid and excluded: {mc.outside_grid_count}.",
        f"Clustered incidents at high-density nodes: {_share(mc.clustered_high_share)}; "
        f"noise incidents at high-density nodes: {_share(mc.noise_high_share)}.",
    ), ((
        ("", "KDE high density", "KDE not high", "Total (eligible)"),
        ("DBSCAN clustered", str(mc.clustered_high), str(mc.clustered_not_high), str(mc.clustered_eligible)),
        ("DBSCAN noise", str(mc.noise_high), str(mc.noise_not_high), str(mc.noise_eligible)),
        ("Total (eligible)", str(mc.high_density_eligible), str(mc.not_high_density_eligible), str(mc.eligible_count)),
    ),)))

    category_tables = tuple(
        ((column, "Incidents"),) + tuple((str(k), str(v)) for k, v in counts.items())
        for column, counts in summary.by_category.items()
    )
    sections.append(ReportSection("Incidents by category", (
        "All accepted incidents." if category_tables else "No severity or incident_type column in this dataset.",
    ), category_tables))

    sections.append(ReportSection("Limitations and notes", LIMITATIONS + tuple(summary.notes) + tuple(mc.notes)))
    return sections


def _require_complete(run: AnalysisRun) -> None:
    if not run.dataset.report.is_usable or run.dataset.frame.empty:
        raise AnalysisError("Reports need a usable dataset; this run has no accepted incidents.")
    if run.clusters is None or run.density is None or run.summary is None:
        raise AnalysisError("Reports need a complete run: DBSCAN, KDE and the summary must all be present.")
    if run.summary.method_comparison is None:
        raise AnalysisError("Reports need the DBSCAN/KDE method comparison in the summary.")


def _flatten_config(values: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    rows = []
    for key, value in values.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            rows.extend(_flatten_config(value, f"{name}."))
        else:
            rows.append((name, "none" if value is None else str(value)))
    return rows


def _share(value: float | None) -> str:
    return "not defined (no eligible incidents)" if value is None else f"{value:.1%}"


def _pdf_plain(text: Any) -> str:
    """Map text to the PDF font's character set; unsupported characters become [U+XXXX]."""
    out = []
    for ch in str(text).replace("≥", ">=").replace("≤", "<="):
        if ch in "\n\t":
            out.append(" ")
            continue
        try:
            ch.encode(PDF_ENCODING)
            if ord(ch) < 32:
                raise UnicodeEncodeError(PDF_ENCODING, ch, 0, 1, "control character")
            out.append(ch)
        except UnicodeEncodeError:
            out.append(f"[U+{ord(ch):04X}]")
    return "".join(out)


def pdf_markup(text: Any) -> str:
    """Safe ReportLab Paragraph markup for user or report text (font-mapped, then XML-escaped)."""
    return escape(_pdf_plain(text))


def _story(sections: list[ReportSection], width: float) -> list:
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["BodyText"], fontSize=7.5, leading=9)
    story: list = [Paragraph("Hotspot Identification and Spatial Analysis - run report", styles["Title"])]
    for section in sections:
        story.append(Paragraph(pdf_markup(section.heading), styles["Heading2"]))
        for text in section.paragraphs:
            story.append(Paragraph(pdf_markup(text), styles["BodyText"]))
        for table in section.tables:
            columns = len(table[0])
            data = [[Paragraph(pdf_markup(value), cell) for value in row] for row in table]
            flowable = Table(data, colWidths=[width / columns] * columns, repeatRows=1)
            flowable.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.extend([Spacer(1, 4), flowable, Spacer(1, 6)])
    return story
