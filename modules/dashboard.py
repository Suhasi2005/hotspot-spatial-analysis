"""Streamlit page renderers. Owner: Member 4 (Dashboard).

The only module (besides app.py) allowed to import Streamlit. Pages read from
AnalysisRun / CleanDataset objects and call app_controller; they hold no
analytical logic.
"""

from __future__ import annotations

import streamlit as st

from modules.app_controller import load_and_validate
from modules.contracts import CleanDataset, DataValidationError
from modules.data_manager import list_sample_datasets
from modules.data_validator import summarize_quality

PAGES: tuple[str, ...] = ("Data", "Clusters (DBSCAN)", "Density (KDE)", "Summary", "History & Reports")
PREVIEW_ROWS = 100


def render_page(name: str) -> None:
    """Render one page. Pages other than Data are placeholders until their stage lands."""
    if name == "Data":
        render_data_page()
        return
    st.header(name)
    st.info("Not implemented yet — see docs/development_plan.md for the stage that builds this page.")


def render_data_page() -> None:
    """Load a CSV (sample or upload), validate it, and show the quality report."""
    st.header("Data")
    samples = list_sample_datasets()
    mode = st.radio("Source", ("Upload a CSV", "Sample dataset"), horizontal=True)

    source = None
    if mode == "Sample dataset":
        if not samples:
            st.info("No sample datasets in data/sample yet.")
        else:
            source = st.selectbox("Sample file", samples, format_func=lambda p: p.name)
    else:
        source = st.file_uploader("CSV file", type=["csv"])

    if source is None:
        st.session_state.pop("dataset", None)
        return

    try:
        dataset = load_and_validate(source)
    except DataValidationError as exc:
        st.session_state.pop("dataset", None)
        st.error(f"This file cannot be used: {exc}")
        return

    st.session_state["dataset"] = dataset
    _render_validation(dataset)


def _render_validation(dataset: CleanDataset) -> None:
    report = dataset.report
    total, accepted, rejected = st.columns(3)
    total.metric("Rows in file", f"{report.total_rows:,}")
    accepted.metric("Accepted", f"{report.valid_rows:,}")
    rejected.metric("Rejected", f"{report.rejected_rows:,}")

    if not report.is_usable:
        st.error(
            "No valid rows remain, so this dataset is unusable. "
            "Spatial analysis will not run. Fix the issues below and upload again."
        )
    elif report.rejected_rows:
        st.warning(f"{report.rejected_rows:,} row(s) were rejected and excluded from analysis.")
    else:
        st.success("All rows passed validation.")

    if report.issues:
        st.subheader("Validation issues")
        st.caption("Row numbers are 0-based data rows (row 0 = first line after the header).")
        st.dataframe(summarize_quality(report), hide_index=True, width="stretch")

    present = ", ".join(report.optional_columns_present) or "none"
    extra = ", ".join(report.extra_columns_preserved) or "none"
    st.caption(f"Optional columns present: {present}. Extra columns preserved: {extra}.")

    if report.is_usable:
        st.subheader(f"Accepted rows (first {min(PREVIEW_ROWS, report.valid_rows):,})")
        st.dataframe(dataset.frame.head(PREVIEW_ROWS), width="stretch")
