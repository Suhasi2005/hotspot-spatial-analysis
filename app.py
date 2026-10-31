"""Streamlit entry point: `streamlit run app.py`.

Navigation only. Pages live in modules/dashboard.py; workflow in
modules/app_controller.py. The sidebar is: brand, page links, then whatever
the page adds (dataset status, analysis parameters, display filters).
"""

import streamlit as st

from modules.dashboard import BRAND_NAME, BRAND_TAGLINE, PAGE_INFO, PAGE_LINKS_KEY, PAGES, render_page
from modules.ui_theme import NAV_ACTIVE_KEY, SHELL_CSS


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
    st.html(f"<style>{SHELL_CSS}</style>")          # static styling only; no user data
    st.sidebar.markdown(f"### {BRAND_NAME}")
    st.sidebar.caption(BRAND_TAGLINE)
    for page in pages:
        if page.url_path == current.url_path:
            with st.sidebar.container(key=NAV_ACTIVE_KEY):   # teal background via SHELL_CSS
                st.page_link(page, width="stretch")
        else:
            st.sidebar.page_link(page, width="stretch")
    st.sidebar.divider()
    current.run()


if __name__ == "__main__":
    main()
