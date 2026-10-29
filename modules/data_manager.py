"""Dataset loading and listing. Owner: Member 1 (Data Management)."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from config.settings import MAX_UPLOAD_ROWS, SAMPLE_DATA_DIR, SUPPORTED_UPLOAD_EXTENSIONS
from modules.contracts import DataValidationError


def list_sample_datasets(directory: Path = SAMPLE_DATA_DIR) -> list[Path]:
    """Return the sample/demo CSV files available under data/sample."""
    return sorted(p for p in directory.glob("*") if p.suffix.lower() in SUPPORTED_UPLOAD_EXTENSIONS)


def load_raw_dataset(
    source: Path | BinaryIO,
    source_name: str | None = None,
    max_rows: int = MAX_UPLOAD_ROWS,
) -> tuple[pd.DataFrame, str]:
    """Read a CSV from disk or an uploaded file object without altering values.

    Every cell is read as text exactly as written: no NA-guessing, so blank
    fields arrive as "" and whitespace-only IDs keep their whitespace. Type
    interpretation is left to data_validator. Row index i is the i-th data
    record, 0-based (file line i + 2 when the file has no blank lines and no
    quoted field spans lines). Completely blank lines are not records and are
    skipped; a row with a different number of fields than the header is refused.

    Returns (raw_frame, source_name). Raises DataValidationError for a missing,
    unsupported, unreadable, empty, malformed, or over-limit file. Columns that
    are present are never renamed; a duplicated header name is refused rather
    than silently suffixed by pandas.
    """
    name = source_name or _default_name(source)
    if Path(name).suffix.lower() not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise DataValidationError(
            f"Unsupported file type for {name!r}; expected one of {', '.join(SUPPORTED_UPLOAD_EXTENSIONS)}."
        )

    raw_bytes = _read_bytes(source, name)
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataValidationError(f"{name!r} is not valid UTF-8 text: {exc.reason} at byte {exc.start}.") from exc
    if not text.strip():
        raise DataValidationError(f"{name!r} is empty: no header row found.")

    # The csv module (not pandas.read_csv) is used so that a row with the wrong
    # number of fields is refused; pandas would silently pad short rows or turn
    # the first column into an index when every row has one extra field.
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
        duplicated = sorted({h for h in header if header.count(h) > 1})
        if duplicated:
            raise DataValidationError(f"{name!r} has duplicated column names: {', '.join(duplicated)}.")
        rows: list[list[str]] = []
        bad_lines: list[int] = []
        for row in reader:
            if not row:                      # blank line: no data, not a record
                continue
            if len(row) != len(header):
                bad_lines.append(reader.line_num)
                continue
            rows.append(row)
            if len(rows) > max_rows:
                raise DataValidationError(
                    f"{name!r} has more than {max_rows:,} rows; split it or raise MAX_UPLOAD_ROWS."
                )
    except csv.Error as exc:
        raise DataValidationError(f"{name!r} is not a well-formed CSV (line {reader.line_num}): {exc}") from exc

    if bad_lines:
        shown = ", ".join(str(n) for n in bad_lines[:10]) + (", ..." if len(bad_lines) > 10 else "")
        raise DataValidationError(
            f"{name!r} is not a well-formed CSV: {len(bad_lines)} row(s) do not have "
            f"{len(header)} fields (file line(s) {shown})."
        )
    return pd.DataFrame(rows, columns=header, dtype=str), name


def _default_name(source: Path | BinaryIO) -> str:
    if isinstance(source, (str, Path)):
        return Path(source).name
    return getattr(source, "name", None) or "uploaded.csv"


def _read_bytes(source: Path | BinaryIO, name: str) -> bytes:
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise DataValidationError(f"File not found: {path.name!r}.")
        if not path.is_file():
            raise DataValidationError(f"{path.name!r} is not a regular file.")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise DataValidationError(f"Cannot read {name!r}: {exc.strerror}.") from exc
    try:
        data = source.read()
    except OSError as exc:
        raise DataValidationError(f"Cannot read {name!r}: {exc}.") from exc
    if isinstance(data, str):
        data = data.encode("utf-8")
    return data
