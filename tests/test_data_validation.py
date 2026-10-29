import re
from pathlib import Path

import pytest

from config.settings import LATITUDE_RANGE, LONGITUDE_RANGE, OPTIONAL_COLUMNS, REQUIRED_COLUMNS, StudyArea
from modules.data_manager import list_sample_datasets

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


@pytest.mark.skip(reason="Stage 2: validate_and_clean not implemented")
def test_invalid_coordinates_are_rejected(synthetic_raw_frame):
    from modules.data_validator import validate_and_clean

    clean = validate_and_clean(synthetic_raw_frame, "synthetic")
    assert clean.report.valid_rows == 3
    assert clean.report.rejected_rows == 2
