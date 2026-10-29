import re
from pathlib import Path

import pandas as pd
import pytest

from config.settings import LATITUDE_RANGE, LONGITUDE_RANGE, OPTIONAL_COLUMNS, REQUIRED_COLUMNS, StudyArea
from modules.contracts import DataValidationError
from modules.data_manager import list_sample_datasets
from modules.data_validator import summarize_quality, validate_and_clean

SPEC_PATH = Path(__file__).resolve().parent.parent / "docs" / "dataset_specification.md"


def _spec_table_columns(section: str) -> tuple[str, ...]:
    """Backticked names in the first cell of each row of a '## <section>' table."""
    text = SPEC_PATH.read_text(encoding="utf-8")
    body = text.split(f"## {section}", 1)[1].split("\n## ", 1)[0]
    return tuple(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", body, flags=re.MULTILINE))


def test_config_columns_match_dataset_specification():
    assert _spec_table_columns("Required columns") == REQUIRED_COLUMNS
    assert _spec_table_columns("Optional columns") == OPTIONAL_COLUMNS


def test_list_sample_datasets_returns_sorted_csv_only(tmp_path):
    for name in ("b.csv", "a.CSV", "notes.txt", "README.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert [p.name for p in list_sample_datasets(tmp_path)] == ["a.CSV", "b.csv"]


def test_list_sample_datasets_empty_directory(tmp_path):
    assert list_sample_datasets(tmp_path) == []


def test_required_columns_match_contract():
    assert REQUIRED_COLUMNS == ("incident_id", "latitude", "longitude")


def test_optional_columns_do_not_overlap_required():
    assert not set(OPTIONAL_COLUMNS) & set(REQUIRED_COLUMNS)


def test_coordinate_ranges_are_legal():
    assert LATITUDE_RANGE == (-90.0, 90.0)
    assert LONGITUDE_RANGE == (-180.0, 180.0)


def test_study_area_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        StudyArea("bad", min_lat=24.0, max_lat=23.0, min_lon=72.0, max_lon=73.0)


def test_invalid_coordinates_are_rejected(synthetic_raw_frame):
    clean = validate_and_clean(synthetic_raw_frame, "synthetic")
    assert clean.report.valid_rows == 3
    assert clean.report.rejected_rows == 2


# --- validate_and_clean ------------------------------------------------------


def _frame(rows, columns=("incident_id", "latitude", "longitude")):
    """Text-only frame, as load_raw_dataset produces."""
    return pd.DataFrame([[str(v) for v in r] for r in rows], columns=list(columns), dtype=str)


def _issues(dataset):
    return {i.code: i.row_indices for i in dataset.report.issues}


def _assert_accounting(dataset):
    """Counts agree and each rejected row appears under exactly one error issue."""
    report = dataset.report
    error_rows = [r for i in report.issues if i.severity == "error" for r in i.row_indices]
    assert len(error_rows) == len(set(error_rows)) == report.rejected_rows
    assert report.valid_rows + report.rejected_rows == report.total_rows
    assert len(dataset.frame) == report.valid_rows
    assert not set(error_rows) & set(dataset.frame.index)


def test_valid_dataset_is_fully_accepted_and_typed():
    raw = _frame([["A", "23.0", "72.5"], ["B", " 23.1 ", "72.6"]])
    dataset = validate_and_clean(raw, "synthetic")
    assert dataset.report.is_usable and dataset.report.rejected_rows == 0
    assert dataset.report.issues == []
    assert dataset.frame["latitude"].dtype == "float64"
    assert dataset.frame["longitude"].tolist() == [72.5, 72.6]
    assert dataset.frame["incident_id"].tolist() == ["A", "B"]
    assert raw.loc[1, "latitude"] == " 23.1 "            # input not mutated
    _assert_accounting(dataset)


def test_missing_required_column_raises_with_hint():
    raw = _frame([["A", "1", "2"]], columns=("incident_id", "Latitude ", "longitude"))
    with pytest.raises(DataValidationError, match=r"latitude.*'Latitude ' looks like 'latitude'"):
        validate_and_clean(raw, "synthetic")


def test_missing_optional_columns_are_reported_absent_not_invented():
    dataset = validate_and_clean(_frame([["A", "1", "2"]]), "synthetic")
    assert dataset.report.optional_columns_present == []
    assert not set(OPTIONAL_COLUMNS) & set(dataset.frame.columns)


def test_optional_and_extra_columns_are_coerced_and_preserved():
    cols = ("incident_id", "latitude", "longitude", "incident_date", "severity", "location_name", "source_ref")
    raw = _frame(
        [
            ["A", "1", "2", "2024-03-05", " major ", " Ring Rd ", "x1"],
            ["B", "1", "2", "05/03/2024", "minor", "", "x2"],
            ["C", "1", "2", "", "", "", "x3"],
        ],
        columns=cols,
    )
    dataset = validate_and_clean(raw, "synthetic")
    frame = dataset.frame
    assert dataset.report.optional_columns_present == ["incident_date", "location_name", "severity"]  # config order
    assert dataset.report.extra_columns_preserved == ["source_ref"]
    assert str(frame.loc[0, "incident_date"].date()) == "2024-03-05"
    assert pd.isna(frame.loc[1, "incident_date"]) and pd.isna(frame.loc[2, "incident_date"])
    assert frame.loc[0, "severity"] == "major" and pd.isna(frame.loc[2, "severity"])
    assert frame.loc[0, "location_name"] == " Ring Rd "   # kept as given
    assert frame["source_ref"].tolist() == ["x1", "x2", "x3"]
    # ambiguous non-ISO date -> warning, row kept; blank date is not a warning
    assert _issues(dataset) == {"UNPARSEABLE_DATE": [1]}
    assert dataset.report.valid_rows == 3


def test_missing_and_blank_ids_are_rejected():
    raw = pd.DataFrame(
        {"incident_id": [None, "", "   ", "A"], "latitude": ["1"] * 4, "longitude": ["2"] * 4}
    )
    dataset = validate_and_clean(raw, "synthetic")
    assert _issues(dataset) == {"MISSING_ID": [0, 1, 2]}
    assert dataset.frame["incident_id"].tolist() == ["A"]
    _assert_accounting(dataset)


def test_duplicate_ids_trimmed_and_case_sensitive():
    raw = _frame(
        [["A1", "1", "2"], [" A1 ", "1", "2"], ["a1", "1", "2"], ["A1", "1", "2"], ["B", "1", "2"]]
    )
    dataset = validate_and_clean(raw, "synthetic")
    dup = [i for i in dataset.report.issues if i.code == "DUPLICATE_ID"]
    assert len(dup) == 1
    assert dup[0].row_indices == [1, 3]
    assert "'A1'" in dup[0].message and "row 0" in dup[0].message
    assert dataset.frame["incident_id"].tolist() == ["A1", "a1", "B"]   # 'a1' is a different ID
    _assert_accounting(dataset)


def test_duplicate_whose_first_occurrence_has_invalid_coordinates():
    raw = _frame([["A", "", "2"], ["A", "1", "2"], ["A", "1", "2"]])
    dataset = validate_and_clean(raw, "synthetic")
    # First occurrence holds the ID (documented rule) and is rejected for coordinates;
    # later rows stay DUPLICATE_ID — they are not promoted. Each row counted once.
    assert _issues(dataset) == {"DUPLICATE_ID": [1, 2], "MISSING_COORDINATE": [0]}
    assert dataset.report.valid_rows == 0 and not dataset.report.is_usable
    _assert_accounting(dataset)


def test_id_checks_run_before_coordinate_checks():
    raw = _frame([["", "999", "2"], ["A", "1", "2"], ["A", "abc", "2"]])
    dataset = validate_and_clean(raw, "synthetic")
    assert _issues(dataset) == {"MISSING_ID": [0], "DUPLICATE_ID": [2]}
    _assert_accounting(dataset)


@pytest.mark.parametrize(
    "lat,lon,code",
    [
        ("", "72.5", "MISSING_COORDINATE"),
        ("23.0", "   ", "MISSING_COORDINATE"),
        ("23.0N", "72.5", "NON_NUMERIC_COORDINATE"),
        ("23,0", "72.5", "NON_NUMERIC_COORDINATE"),
        ("NaN", "72.5", "NON_NUMERIC_COORDINATE"),
        ("inf", "72.5", "NON_FINITE_COORDINATE"),
        ("23.0", "-Infinity", "NON_FINITE_COORDINATE"),
        ("90.0001", "72.5", "LAT_OUT_OF_RANGE"),
        ("-91", "72.5", "LAT_OUT_OF_RANGE"),
        ("23.0", "180.5", "LON_OUT_OF_RANGE"),
        ("23.0", "-200", "LON_OUT_OF_RANGE"),
    ],
)
def test_invalid_coordinate_codes(lat, lon, code):
    dataset = validate_and_clean(_frame([["A", lat, lon], ["B", "23.0", "72.5"]]), "synthetic")
    assert _issues(dataset) == {code: [0]}
    _assert_accounting(dataset)


def test_boundary_coordinates_are_legal():
    raw = _frame([["A", "90", "180"], ["B", "-90", "-180"]])
    assert validate_and_clean(raw, "synthetic").report.valid_rows == 2


def test_row_with_several_bad_fields_is_counted_once():
    raw = _frame([["A", "abc", "999"], ["B", "inf", ""]])
    dataset = validate_and_clean(raw, "synthetic")
    assert dataset.report.rejected_rows == 2
    assert _issues(dataset) == {"MISSING_COORDINATE": [1], "NON_NUMERIC_COORDINATE": [0]}
    _assert_accounting(dataset)


def test_null_island_is_a_warning_and_row_is_kept():
    dataset = validate_and_clean(_frame([["A", "0", "0"]]), "synthetic")
    assert _issues(dataset) == {"NULL_ISLAND": [0]}
    assert dataset.report.valid_rows == 1 and dataset.report.rejected_rows == 0


def test_study_area_rejects_points_outside():
    area = StudyArea("box", min_lat=22.9, max_lat=23.2, min_lon=72.4, max_lon=72.7)
    raw = _frame([["A", "23.0", "72.5"], ["B", "72.5", "23.0"]])   # B: lat/lon swapped
    dataset = validate_and_clean(raw, "synthetic", study_area=area)
    assert _issues(dataset) == {"OUTSIDE_STUDY_AREA": [1]}
    _assert_accounting(dataset)


def test_zero_valid_rows_returns_unusable_dataset():
    dataset = validate_and_clean(_frame([["", "1", "2"], ["B", "x", "2"]]), "synthetic")
    assert dataset.report.is_usable is False
    assert dataset.frame.empty
    assert list(dataset.frame.columns)[:3] == ["incident_id", "latitude", "longitude"]
    _assert_accounting(dataset)


def test_header_only_frame_is_unusable_not_an_error():
    dataset = validate_and_clean(_frame([]), "synthetic")
    assert dataset.report.total_rows == 0 and dataset.report.is_usable is False


def test_usable_and_unusable_are_distinguishable():
    good = validate_and_clean(_frame([["A", "1", "2"]]), "synthetic")
    bad = validate_and_clean(_frame([["A", "", "2"]]), "synthetic")
    assert good.report.is_usable and not bad.report.is_usable


def test_clean_frame_keeps_source_row_index():
    raw = _frame([["A", "x", "2"], ["B", "1", "2"], ["C", "1", "2"]])
    assert list(validate_and_clean(raw, "synthetic").frame.index) == [1, 2]


def test_non_consecutive_source_index_is_reported_and_preserved():
    """Row identifiers are traceability labels, not positions: issues and the
    clean frame must carry the caller's labels, never 0..n-1 positions."""
    raw = _frame([["A", "1", "2"], ["", "1", "2"], ["A", "1", "2"], ["B", "x", "2"], ["C", "3", "4"]])
    raw.index = [10, 25, 7, 99, 42]                     # non-consecutive, unsorted
    dataset = validate_and_clean(raw, "synthetic")
    assert _issues(dataset) == {"MISSING_ID": [25], "DUPLICATE_ID": [7], "NON_NUMERIC_COORDINATE": [99]}
    assert "row 10" in next(i.message for i in dataset.report.issues if i.code == "DUPLICATE_ID")
    assert list(dataset.frame.index) == [10, 42]        # input order kept, labels kept
    assert dataset.frame["incident_id"].tolist() == ["A", "C"]
    _assert_accounting(dataset)


def test_clean_frame_index_has_gaps_after_rejections():
    raw = _frame([["A", "1", "2"], ["B", "", "2"], ["C", "1", "2"], ["D", "999", "2"], ["E", "1", "2"]])
    frame = validate_and_clean(raw, "synthetic").frame
    assert list(frame.index) == [0, 2, 4]               # not renumbered
    assert frame.iloc[1]["incident_id"] == "C"          # position 1 is label 2


def test_all_invalid_dataset_through_every_rule_is_unusable():
    raw = _frame([["", "1", "2"], ["A", "", "2"], ["A", "1", "2"], ["C", "x", "2"],
                  ["D", "inf", "2"], ["E", "91", "2"], ["F", "1", "181"]])
    dataset = validate_and_clean(raw, "synthetic")
    assert _issues(dataset) == {
        "MISSING_ID": [0], "DUPLICATE_ID": [2], "MISSING_COORDINATE": [1], "NON_NUMERIC_COORDINATE": [3],
        "NON_FINITE_COORDINATE": [4], "LAT_OUT_OF_RANGE": [5], "LON_OUT_OF_RANGE": [6],
    }
    assert dataset.report.is_usable is False and dataset.frame.empty
    assert dataset.report.rejected_rows == dataset.report.total_rows == 7
    _assert_accounting(dataset)


def test_summarize_quality_table():
    raw = _frame([["A", "x", "2"], ["A", "1", "2"]] + [["", "1", "2"]] * 25)
    table = summarize_quality(validate_and_clean(raw, "synthetic").report)
    assert list(table.columns) == ["severity", "code", "affected_rows", "rows", "message"]
    assert table["code"].tolist() == ["MISSING_ID", "DUPLICATE_ID", "NON_NUMERIC_COORDINATE"]
    assert table.loc[0, "affected_rows"] == 25 and table.loc[0, "rows"].endswith(", ...")
    assert summarize_quality(validate_and_clean(_frame([["A", "1", "2"]]), "s").report).empty
