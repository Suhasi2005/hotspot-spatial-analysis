"""Streamlit entry point: `streamlit run app.py`.

Navigation only. Pages live in modules/dashboard.py; workflow in
modules/app_controller.py. The shell (ui_components.app_shell) is: brand, page
links, a page bar on phones; pages then add to the sidebar whatever they need
(dataset status, analysis parameters, display filters).
"""

import streamlit as st

from modules.dashboard import BRAND_NAME, BRAND_TAGLINE, PAGE_INFO, PAGES, render_page
from modules.ui_components import PAGE_LINKS_KEY, app_shell


def _page_callable(name: str):
    def page() -> None:
        render_page(name)

    page.__name__ = f"page_{PAGE_INFO[name][2]}"   # unique, stable identity per page
    return page


def main() -> None:
    st.set_page_config(page_title=BRAND_NAME, page_icon=":material/travel_explore:", layout="wide")
    pages = [
        st.Page(_page_callable(name), title=PAGE_INFO[name][0], icon=PAGE_INFO[name][1],
                url_path=PAGE_INFO[name][2], default=(index == 0))
        for index, name in enumerate(PAGES)
    ]
    current = st.navigation(pages, position="hidden")
    st.session_state[PAGE_LINKS_KEY] = dict(zip(PAGES, pages))   # for links inside pages
    app_shell(pages, current, BRAND_NAME, BRAND_TAGLINE)
    current.run()


if __name__ == "__main__":
    main()
