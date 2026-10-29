"""Streamlit entry point: `streamlit run app.py`.

Navigation only. Pages live in modules/dashboard.py; workflow in
modules/app_controller.py.
"""

import streamlit as st

from modules.dashboard import PAGES, render_page


def main() -> None:
    st.set_page_config(page_title="Hotspot Spatial Analysis", layout="wide")
    st.sidebar.title("Hotspot Spatial Analysis")
    page = st.sidebar.radio("Navigate", PAGES)
    render_page(page)


if __name__ == "__main__":
    main()
