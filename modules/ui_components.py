"""Reusable Streamlit components shared by every page, plus the application shell.

Besides dashboard.py, this is the only module allowed to import Streamlit. It
holds presentation only: no analysis, no storage, and no page-specific logic.
Styling comes from ui_theme.SHELL_CSS, which targets the keyed containers made here.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from modules.ui_theme import (
    EMPTY_STATE_PREFIX,
    KPI_KEY_PREFIX,
    MOBILE_NAV_ACTIVE_KEY,
    MOBILE_NAV_KEY,
    NAV_ACTIVE_KEY,
    PANEL_PREFIX,
    SHELL_CSS,
)

KPI_PER_ROW = 4
STATUS_KPI_LABELS = ("Analysis status", "Validation status")
# Session-state key for {page name: st.Page}, set by app.py so pages can link to each other.
PAGE_LINKS_KEY = "page_links"


# --- application shell -------------------------------------------------------------------


def app_shell(pages: list[Any], current: Any, brand: str, tagline: str) -> None:
    """Shared styling and navigation: sidebar on wide screens, a page bar on phones."""
    st.html(f"<style>{SHELL_CSS}</style>")          # static styling only; no user data
    st.sidebar.markdown(f"### {brand}")
    st.sidebar.caption(tagline)
    for page in pages:
        if page.url_path == current.url_path:
            with st.sidebar.container(key=NAV_ACTIVE_KEY):
                st.page_link(page, width="stretch")
        else:
            st.sidebar.page_link(page, width="stretch")
    st.sidebar.divider()
    _mobile_navigation(pages, current)


def _mobile_navigation(pages: list[Any], current: Any) -> None:
    """Every page in one tap on phones, where Streamlit hides the sidebar; CSS hides this on wider screens."""
    with st.container(horizontal=True, key=MOBILE_NAV_KEY):
        for page in pages:
            label = page.title.split(" & ")[0]
            if page.url_path == current.url_path:
                with st.container(key=MOBILE_NAV_ACTIVE_KEY):
                    st.page_link(page, label=label)
            else:
                st.page_link(page, label=label)


def page_header(title: str, description: str) -> None:
    """Page title plus its one-line description."""
    st.header(title)
    st.caption(description)


def page_link(page: str, label: str) -> None:
    """Link to another page; skipped when no page objects are registered (pages run alone)."""
    target = st.session_state.get(PAGE_LINKS_KEY, {}).get(page)
    if target is not None:
        st.page_link(target, label=label, icon=":material/arrow_forward:")


# --- containers ----------------------------------------------------------------------------


def panel(name: str):
    """Elevated card used for any grouped content; `name` must be unique on the page."""
    return st.container(key=f"{PANEL_PREFIX}{name}")


def empty_state(key: str, icon: str, heading: str, message: str, show=st.info,
                link: tuple[str, str] | None = None) -> None:
    """Card for "nothing here yet": heading, the existing message, and an optional next step."""
    with st.container(key=f"{EMPTY_STATE_PREFIX}{key}"):
        st.markdown(f"#### {icon} {heading}")
        show(message)
        if link is not None:
            page_link(*link)


# --- KPI cards -----------------------------------------------------------------------------


def kpi_strip(items: list[tuple[str, str]]) -> None:
    """KPI cards from (label, value) pairs, at most KPI_PER_ROW per row.

    Values are shown exactly as given; callers pass existing values only and use
    NOT_RUN when an analysis has not produced one.

    Each card is an st.metric inside a keyed container (see kpi_key) that
    ui_theme.SHELL_CSS styles as a card; status values become a coloured
    badge whose text still states the status.
    """
    for row in kpi_rows(items):
        for column, (label, value) in zip(st.columns(KPI_PER_ROW), row):
            with column.container(key=kpi_key(label, value)):
                st.metric(label, value)


def kpi_grid(items: list[tuple[str, str]], key: str) -> None:
    """KPI cards in a wrapping row: same cards as kpi_strip, but two across on phones."""
    with st.container(horizontal=True, wrap=True, key=key):
        for label, value in items:
            with st.container(key=kpi_key(label, value)):
                st.metric(label, value)


def kpi_rows(items: list[tuple[str, str]], per_row: int = KPI_PER_ROW) -> list[list[tuple[str, str]]]:
    """Split KPI (label, value) pairs into rows of at most `per_row`."""
    return [items[i:i + per_row] for i in range(0, len(items), per_row)]


def kpi_tone(label: str, value: str) -> str | None:
    """Badge tone for a status KPI (success / warning / error / info); None for other KPIs.

    Display only: the value text itself is unchanged and always shown.
    """
    if label not in STATUS_KPI_LABELS:
        return None
    if value in ("Complete", "Ready"):
        return "success"
    if value.startswith("Partial") or value == "Ready with rejections":
        return "warning"
    if value in ("Failed", "Unusable", "Dataset unusable"):
        return "error"
    return "info"                                                      # NOT_RUN and anything unexpected


def kpi_key(label: str, value: str) -> str:
    """Container key for one KPI card; status cards carry their badge tone for the CSS."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in label.lower())
    tone = kpi_tone(label, value)
    return f"{KPI_KEY_PREFIX}{f'badge_{tone}_' if tone else 'card_'}{slug}"
