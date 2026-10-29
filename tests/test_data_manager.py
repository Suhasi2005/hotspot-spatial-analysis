"""Loader tests. All files are synthetic and written to pytest's tmp_path."""

import io

import pytest

from modules.app_controller import load_and_validate
from modules.contracts import DataValidationError
from modules.data_manager import load_raw_dataset


def _write(tmp_path, text: str, name: str = "incidents.csv", encoding: str = "utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def test_loads_every_cell_as_text_without_na_guessing(tmp_path):
    path = _write(tmp_path, "incident_id,latitude,longitude,note\nA1,23.0,72.5,NA\n  ,,72.6,\n")
    frame, name = load_raw_dataset(path)
    assert name == "incidents.csv"
    assert list(frame.columns) == ["incident_id", "latitude", "longitude", "note"]
    assert frame.loc[0, "latitude"] == "23.0"          # still text
    assert frame.loc[0, "note"] == "NA"                # not turned into NaN
    assert frame.loc[1, "incident_id"] == "  "         # whitespace preserved for the validator
    assert frame.loc[1, "latitude"] == ""              # blank field stays blank
    assert list(frame.index) == [0, 1]


def test_whitespace_only_id_from_csv_is_rejected_as_missing_id(tmp_path):
    path = _write(tmp_path, "incident_id,latitude,longitude\n   ,23.0,72.5\nB2,23.1,72.6\n")
    dataset = load_and_validate(path)
    codes = {i.code: i.row_indices for i in dataset.report.issues}
    assert codes == {"MISSING_ID": [0]}
    assert dataset.report.valid_rows == 1


def test_utf8_bom_does_not_corrupt_first_column(tmp_path):
    path = _write(tmp_path, "incident_id,latitude,longitude\nA,1,2\n", encoding="utf-8-sig")
    frame, _ = load_raw_dataset(path)
    assert frame.columns[0] == "incident_id"


def test_file_object_upload_uses_its_name():
    upload = io.BytesIO(b"incident_id,latitude,longitude\nA,1,2\n")
    upload.name = "upload.csv"
    frame, name = load_raw_dataset(upload)
    assert name == "upload.csv" and len(frame) == 1


def test_blank_lines_are_not_records(tmp_path):
    frame, _ = load_raw_dataset(_write(tmp_path, "incident_id,latitude,longitude\nA,1,2\n\nB,3,4\n"))
    assert frame["incident_id"].tolist() == ["A", "B"] and list(frame.index) == [0, 1]


def test_uppercase_extension_is_accepted(tmp_path):
    frame, name = load_raw_dataset(_write(tmp_path, "incident_id,latitude,longitude\nA,1,2\n", name="DATA.CSV"))
    assert name == "DATA.CSV" and len(frame) == 1


def test_header_only_csv_loads_with_zero_rows(tmp_path):
    frame, _ = load_raw_dataset(_write(tmp_path, "incident_id,latitude,longitude\n"))
    assert len(frame) == 0


@pytest.mark.parametrize(
    "content,match",
    [
        ("", "empty"),
        ("   \n\n", "empty"),
        ('incident_id,latitude,longitude\nA,1,2,EXTRA\n', "well-formed"),
        ('incident_id,latitude,longitude\nA,1,2\nB,1\n', r"line\(s\) 3"),
        ('incident_id,latitude,longitude\n"A,1,2\n', "well-formed"),
        ("incident_id,latitude,latitude\nA,1,2\n", "duplicated column"),
    ],
)
def test_empty_or_malformed_csv_raises(tmp_path, content, match):
    with pytest.raises(DataValidationError, match=match):
        load_raw_dataset(_write(tmp_path, content))


def test_non_utf8_file_raises(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("incident_id,latitude,longitude\nCafé,1,2\n".encode("latin-1"))
    with pytest.raises(DataValidationError, match="UTF-8"):
        load_raw_dataset(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(DataValidationError, match="not found"):
        load_raw_dataset(tmp_path / "nope.csv")


def test_directory_is_not_readable_as_csv(tmp_path):
    folder = tmp_path / "folder.csv"
    folder.mkdir()
    with pytest.raises(DataValidationError, match="not a regular file"):
        load_raw_dataset(folder)


def test_unsupported_extension_raises(tmp_path):
    with pytest.raises(DataValidationError, match="Unsupported"):
        load_raw_dataset(_write(tmp_path, "a,b\n1,2\n", name="data.xlsx"))


def test_row_limit_raises_instead_of_truncating(tmp_path):
    rows = "".join(f"I{i},1,2\n" for i in range(4))
    with pytest.raises(DataValidationError, match="more than 3"):
        load_raw_dataset(_write(tmp_path, "incident_id,latitude,longitude\n" + rows), max_rows=3)


def test_header_only_csv_is_unusable_through_controller(tmp_path):
    dataset = load_and_validate(_write(tmp_path, "incident_id,latitude,longitude\n"))
    report = dataset.report
    assert (report.total_rows, report.valid_rows, report.rejected_rows) == (0, 0, 0)
    assert report.is_usable is False and dataset.frame.empty and report.issues == []


def test_all_invalid_csv_is_unusable_through_controller(tmp_path):
    dataset = load_and_validate(_write(tmp_path, "incident_id,latitude,longitude\n ,1,2\nA,,2\nA,1,2\n"))
    assert dataset.report.is_usable is False
    assert dataset.report.rejected_rows == dataset.report.total_rows == 3


def test_missing_required_column_raises_through_controller(tmp_path):
    with pytest.raises(DataValidationError, match="longitude"):
        load_and_validate(_write(tmp_path, "incident_id,latitude\nA,1\n"))
