"""Schema validation and cleaning. Owner: Member 1 (Data Management)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import (
    LATITUDE_RANGE,
    LONGITUDE_RANGE,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    StudyArea,
)
from modules.contracts import CleanDataset, DataValidationError, ValidationIssue, ValidationReport

# Rejection rules in evaluation order. A row receives only the FIRST code it fails.
REJECTION_ORDER: tuple[str, ...] = (
    "MISSING_ID",
    "DUPLICATE_ID",
    "MISSING_COORDINATE",
    "NON_NUMERIC_COORDINATE",
    "NON_FINITE_COORDINATE",
    "LAT_OUT_OF_RANGE",
    "LON_OUT_OF_RANGE",
    "OUTSIDE_STUDY_AREA",
)

_MESSAGES = {
    "MISSING_ID": "incident_id is missing or blank.",
    "MISSING_COORDINATE": "latitude or longitude is missing or blank.",
    "NON_NUMERIC_COORDINATE": "latitude or longitude is not a decimal number.",
    "NON_FINITE_COORDINATE": "latitude or longitude is infinite.",
    "LAT_OUT_OF_RANGE": f"latitude is outside [{LATITUDE_RANGE[0]}, {LATITUDE_RANGE[1]}].",
    "LON_OUT_OF_RANGE": f"longitude is outside [{LONGITUDE_RANGE[0]}, {LONGITUDE_RANGE[1]}].",
    "OUTSIDE_STUDY_AREA": "point lies outside the configured study area.",
    "NULL_ISLAND": "coordinates are exactly (0, 0), which usually means a missing value.",
    "UNPARSEABLE_DATE": "incident_date is not an ISO 8601 date; set to empty (NaT).",
}


def validate_and_clean(
    raw: pd.DataFrame,
    source_name: str,
    study_area: StudyArea | None = None,
) -> CleanDataset:
    """Validate a raw frame against the shared schema and return clean rows.

    Rules (docs/dataset_specification.md):
    - A missing required column raises DataValidationError.
    - Null/blank incident_id -> row rejected (MISSING_ID).
    - Repeated incident_id -> first occurrence kept, later ones rejected
      (DUPLICATE_ID, with their row indices). This is the project's only
      duplicate rule.
    - Coordinates must be numeric, non-null and in legal range, else the row
      is rejected and recorded in the report.
    - Optional columns are coerced; extra columns are preserved; no value is
      imputed.
    - Zero surviving rows does NOT raise: an empty CleanDataset is returned
      with report.is_usable == False.

    Each rejected row is reported under exactly one code: the first rule it
    fails in REJECTION_ORDER. The input frame is not mutated; the returned
    frame keeps the input's row index so every row traces back to its source.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise DataValidationError(_missing_columns_message(missing, list(raw.columns)))

    total = len(raw)
    rejected: dict[object, str] = {}  # row index -> rejection code
    duplicate_issues: list[ValidationIssue] = []

    # 1. Incident IDs: trimmed, case-sensitive, first occurrence (file order) kept.
    ids = raw["incident_id"].map(_trimmed_text)
    for idx in ids.index[ids.isna()]:
        rejected[idx] = "MISSING_ID"
    present = ids.dropna()
    first_seen = present[~present.duplicated(keep="first")]
    first_index = {value: idx for idx, value in first_seen.items()}
    later = present[present.duplicated(keep="first")]
    for value, group in later.groupby(later, sort=False):
        kept = first_index[value]
        duplicate_issues.append(
            ValidationIssue(
                code="DUPLICATE_ID",
                message=(
                    f"incident_id {value!r} repeats row {kept}; row {kept} holds the ID "
                    f"and {len(group)} later row(s) were rejected."
                ),
                row_indices=[int(i) for i in group.index],
            )
        )
        for idx in group.index:
            rejected[idx] = "DUPLICATE_ID"

    # 2. Coordinates, for rows still standing. Latitude is checked before longitude.
    lat = _parse_coordinate(raw["latitude"])
    lon = _parse_coordinate(raw["longitude"])
    for idx in raw.index:
        if idx in rejected:
            continue
        code = _coordinate_code(lat.loc[idx], lon.loc[idx], study_area)
        if code:
            rejected[idx] = code

    # 3. Build the clean frame.
    keep_mask = ~raw.index.isin(list(rejected))
    clean = raw.loc[keep_mask].copy()
    clean["incident_id"] = ids.loc[keep_mask].astype(str)
    clean["latitude"] = lat.loc[keep_mask, "value"].astype("float64")
    clean["longitude"] = lon.loc[keep_mask, "value"].astype("float64")

    warnings: list[ValidationIssue] = []
    null_island = clean.index[(clean["latitude"] == 0.0) & (clean["longitude"] == 0.0)]
    if len(null_island):
        warnings.append(_issue("NULL_ISLAND", null_island, severity="warning"))

    optional_present = [c for c in OPTIONAL_COLUMNS if c in raw.columns]
    for column in optional_present:
        clean[column], bad_rows = _coerce_optional(column, clean[column])
        if len(bad_rows):
            warnings.append(_issue("UNPARSEABLE_DATE", bad_rows, severity="warning"))

    issues = duplicate_issues + _group_rejections(rejected) + warnings
    issues.sort(key=lambda i: (i.severity != "error", _code_rank(i.code)))

    report = ValidationReport(
        total_rows=total,
        valid_rows=len(clean),
        rejected_rows=len(rejected),
        issues=issues,
        optional_columns_present=optional_present,
        extra_columns_preserved=[
            c for c in raw.columns if c not in REQUIRED_COLUMNS and c not in OPTIONAL_COLUMNS
        ],
    )
    if report.valid_rows + report.rejected_rows != report.total_rows:
        raise RuntimeError("Validation accounting error: valid + rejected != total rows.")
    return CleanDataset(frame=clean, source_name=source_name, report=report)


def summarize_quality(report: ValidationReport) -> pd.DataFrame:
    """Flatten a ValidationReport into one row per issue for display/export.

    Columns: severity, code, affected_rows, rows (comma-separated source row
    indices, first 20 then '...'), message.
    """
    rows = []
    for issue in report.issues:
        shown = ", ".join(str(i) for i in issue.row_indices[:20])
        if len(issue.row_indices) > 20:
            shown += ", ..."
        rows.append(
            {
                "severity": issue.severity,
                "code": issue.code,
                "affected_rows": len(issue.row_indices),
                "rows": shown,
                "message": issue.message,
            }
        )
    return pd.DataFrame(rows, columns=["severity", "code", "affected_rows", "rows", "message"])


# --- helpers -----------------------------------------------------------------


def _trimmed_text(value: object) -> str | None:
    """Return the trimmed string, or None if null/blank. Never reinterprets content."""
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA:
        return None
    text = str(value).strip()
    return text or None


def _parse_coordinate(series: pd.Series) -> pd.DataFrame:
    """Per row: value (float, NaN if unusable) and state: ok/missing/non_numeric/non_finite."""
    text = series.map(_trimmed_text)
    value = pd.to_numeric(text, errors="coerce").astype("float64")
    state = pd.Series("ok", index=series.index, dtype=object)
    state[text.isna()] = "missing"
    state[text.notna() & value.isna()] = "non_numeric"
    state[np.isinf(value)] = "non_finite"
    return pd.DataFrame({"value": value, "state": state})


def _coordinate_code(lat: pd.Series, lon: pd.Series, study_area: StudyArea | None) -> str | None:
    for state_code, code in (
        ("missing", "MISSING_COORDINATE"),
        ("non_numeric", "NON_NUMERIC_COORDINATE"),
        ("non_finite", "NON_FINITE_COORDINATE"),
    ):
        if lat["state"] == state_code or lon["state"] == state_code:
            return code
    if not LATITUDE_RANGE[0] <= lat["value"] <= LATITUDE_RANGE[1]:
        return "LAT_OUT_OF_RANGE"
    if not LONGITUDE_RANGE[0] <= lon["value"] <= LONGITUDE_RANGE[1]:
        return "LON_OUT_OF_RANGE"
    if study_area is not None and not (
        study_area.min_lat <= lat["value"] <= study_area.max_lat
        and study_area.min_lon <= lon["value"] <= study_area.max_lon
    ):
        return "OUTSIDE_STUDY_AREA"
    return None


def _coerce_optional(column: str, series: pd.Series) -> tuple[pd.Series, pd.Index]:
    """Coerce one optional column. Returns (new_series, rows with unparseable values)."""
    if column == "incident_date":
        text = series.map(_trimmed_text)
        parsed = pd.to_datetime(text, format="ISO8601", errors="coerce")
        bad = series.index[text.notna() & parsed.isna()]
        return parsed, bad
    if column in ("incident_type", "severity"):
        return series.map(_trimmed_text).astype("category"), pd.Index([])
    return series, pd.Index([])  # location_name: kept as given


def _issue(code: str, rows, severity: str = "error") -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=_MESSAGES[code],
        row_indices=sorted(int(i) for i in rows),
        severity=severity,
    )


def _group_rejections(rejected: dict[object, str]) -> list[ValidationIssue]:
    by_code: dict[str, list[object]] = {}
    for idx, code in rejected.items():
        if code != "DUPLICATE_ID":  # already reported per duplicated ID
            by_code.setdefault(code, []).append(idx)
    return [_issue(code, rows) for code, rows in by_code.items()]


def _code_rank(code: str) -> int:
    return REJECTION_ORDER.index(code) if code in REJECTION_ORDER else len(REJECTION_ORDER)


def _missing_columns_message(missing: list[str], present: list[str]) -> str:
    message = f"Missing required column(s): {', '.join(missing)}."
    hints = [
        f"{p!r} looks like {m!r}"
        for m in missing
        for p in present
        if p != m and p.strip().lower() == m
    ]
    if hints:
        message += " Column names must match exactly: " + "; ".join(hints) + "."
    return message
