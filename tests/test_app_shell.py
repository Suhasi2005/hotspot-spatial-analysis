"""Application shell and shared components tests (Stage 1 dark design system)."""

import ast
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from modules import ui_components, ui_theme
from modules.dashboard import PAGES
from modules.ui_components import PAGE_LINKS_KEY

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def app():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    return at


def _labels(at):
    return [el.proto.label for el in at.get("page_link")]


def test_every_page_is_linked_in_both_sidebar_and_phone_bar(app):
    assert len(_labels(app)) == 2 * len(PAGES)
    assert sorted(set(_labels(app))) == sorted({"Data", "Clusters", "Density", "Summary", "History & Reports", "History"})
    assert list(app.session_state[PAGE_LINKS_KEY]) == list(PAGES)


def test_phone_bar_is_only_shown_below_the_breakpoint():
    css = ui_theme.SHELL_CSS
    rule = f"@media (min-width: {ui_theme.MOBILE_BREAKPOINT_PX}px) {{ .st-key-{ui_theme.MOBILE_NAV_KEY} {{ display: none; }} }}"
    assert rule in css and ui_theme.MOBILE_BREAKPOINT_PX == 768


def test_phone_bar_tabs_are_large_enough_to_tap():
    assert "min-height: 48px" in ui_theme.SHELL_CSS


def test_active_page_uses_a_tint_and_an_accent_bar_on_both_navigations():
    css = ui_theme.SHELL_CSS
    for key in (ui_theme.NAV_ACTIVE_KEY, ui_theme.MOBILE_NAV_ACTIVE_KEY):
        assert f".st-key-{key} a" in css
    assert ui_theme.NAV_ACTIVE_BACKGROUND in css and f"inset 3px 0 0 {ui_theme.ACCENT}" in css


def test_panels_replace_plain_bordered_containers():
    source = (ROOT / "modules" / "dashboard.py").read_text(encoding="utf-8")
    assert "border=True" not in source and "PANEL_PREFIX" not in source


def test_primary_buttons_use_dark_text_on_the_accent():
    assert re.search(r'stBaseButton-primary"\] p \{ color: ' + ui_theme.ON_ACCENT, ui_theme.SHELL_CSS)


def test_filter_chips_use_dark_text_on_the_accent():
    rule = next(line for line in ui_theme.SHELL_CSS.splitlines() if "stMultiSelectTagsContainer" in line)
    assert rule.startswith(f".st-key-{ui_theme.FILTERS_KEY} ") and ui_theme.ON_ACCENT in rule


def test_no_light_theme_colours_remain_in_the_ui_code():
    for name in ("dashboard.py", "ui_components.py", "ui_theme.py"):
        source = (ROOT / "modules" / name).read_text(encoding="utf-8").upper()
        for colour in ("#FFFFFF\"", "#F6F7F9", "#1A2433", "#0E6E8C", "#BBBBBB"):
            assert colour not in source, (name, colour)


def test_components_module_has_no_analysis_imports():
    tree = ast.parse((ROOT / "modules" / "ui_components.py").read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= {"__future__", "typing", "modules.ui_theme"}
    assert ui_components.KPI_PER_ROW == 4


def test_lock_file_pins_the_tested_streamlit_and_every_requirement():
    lock = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    pinned = {line.split("==")[0].lower() for line in lock.splitlines() if "==" in line and not line.startswith("#")}
    assert "streamlit==1.66.1" in lock
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "streamlit>=1.66.1,<2.0" in requirements
    wanted = {re.split(r"[>=<]", line)[0].strip().lower() for line in requirements.splitlines()
              if line.strip() and not line.startswith("#")}
    assert wanted <= pinned
