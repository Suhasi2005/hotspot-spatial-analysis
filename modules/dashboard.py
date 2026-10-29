"""Streamlit page renderers. Owner: Member 4 (Dashboard).

The only module (besides app.py) allowed to import Streamlit. Pages read from
AnalysisRun / CleanDataset objects and call app_controller; they hold no
analytical logic.
"""

from __future__ import annotations

import streamlit as st

PAGES: tuple[str, ...] = ("Data", "Clusters (DBSCAN)", "Density (KDE)", "Summary", "History & Reports")


def render_page(name: str) -> None:
    """Render one page. Every page is a placeholder until its stage lands."""
    st.header(name)
    st.info("Not implemented yet — see docs/development_plan.md for the stage that builds this page.")
