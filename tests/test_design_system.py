"""Design-system and KPI-card tests (Stage 10B Phase 4.2).

Tokens, badge contrast, the static shell CSS, the Streamlit config options and the
KPI tone mapping. Display only: KPI values are checked to be unchanged.
"""

import re
import tomllib
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import modules.dashboard as dashboard
from modules import ui_theme
from modules.dashboard import NOT_RUN
from modules.ui_components import kpi_key, kpi_tone
from modules.data_validator import validate_and_clean

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
SCRIPT = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom modules.dashboard import render_page\nrender_page(PAGE)\n"


def _contrast(fg: str, bg: str) -> float:
    def luminance(hex_colour):
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    light, dark = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# --- tokens ------------------------------------------------------------------------------


def test_surface_spacing_and_radius_tokens():
    assert ui_theme.RADIUS_CARD_PX == 10
    assert ui_theme.SPACING_PX == (4, 8, 12, 16, 24, 32)
    assert (ui_theme.SPACE_XS, ui_theme.SPACE_2XL) == (4, 32)
    assert ui_theme.SHADOW_CARD.startswith("0 1px") and "rgba(2, 8, 16" in ui_theme.SHADOW_CARD
    assert (ui_theme.KPI_LABEL_PX, ui_theme.KPI_LABEL_WEIGHT, ui_theme.METRIC_VALUE_PX) == (12, 500, 28)


@pytest.mark.parametrize("tone", ["success", "warning", "error", "info"])
def test_badges_are_tints_of_the_status_tokens_with_readable_text(tone):
    background, text = ui_theme.BADGE_BACKGROUND[tone], ui_theme.BADGE_TEXT[tone]
    assert re.fullmatch(r"#[0-9A-F]{6}", background) and re.fullmatch(r"#[0-9A-F]{6}", text)
    assert background == ui_theme._mix(ui_theme.STATUS_COLOURS[tone], ui_theme.SURFACE, 0.16)
    assert _contrast(text, background) >= 4.5                                 # WCAG AA for normal text
    assert _contrast(text, ui_theme.SURFACE) >= 4.5


def test_status_and_brand_colours_are_unchanged():
    assert (ui_theme.SUCCESS, ui_theme.WARNING, ui_theme.ERROR, ui_theme.INFO) == ("#20C997", "#E8B44A", "#F06464", "#5CB0F5")
    assert (ui_theme.ACCENT, ui_theme.SIDEBAR_BACKGROUND) == ("#08B8D4", "#091827")


# --- static CSS and config -------------------------------------------------------------------


def test_kpi_css_is_static_scoped_to_keyed_containers_and_uses_tokens():
    css = ui_theme.SHELL_CSS
    assert "<" not in css and "script" not in css.lower() and "javascript" not in css.lower()
    assert '[class*="st-key-kpi_"]' in css and ui_theme.SHADOW_CARD in css and "border-radius: 10px" in css
    for tone in ("success", "warning", "error", "info"):
        assert f'[class*="st-key-kpi_badge_{tone}_"]' in css and ui_theme.BADGE_BACKGROUND[tone] in css
    # every rule starts from a keyed container; no Streamlit element ids or nth-child selectors
    rules = [rule.split("{", 1)[1].strip() if rule.startswith("@media") else rule for rule in css.strip().splitlines()]
    selectors = [rule.split("{")[0].strip() for rule in rules]
    assert all(sel.startswith((".st-key-", '[class*="st-key-')) for sel in selectors)
    assert "#" not in "".join(selectors) and "nth-child" not in css


def test_config_hides_toolbar_and_sets_padding_without_replacing_theme():
    assert CONFIG["client"]["toolbarMode"] == "minimal"
    assert CONFIG["theme"]["paddingTop"] == ui_theme.MAIN_PADDING_TOP == "2rem"
    assert CONFIG["theme"]["sidebar"]["paddingTop"] == ui_theme.SIDEBAR_PADDING_TOP == "1rem"   # sidebar not moved
    assert CONFIG["theme"]["primaryColor"] == ui_theme.ACCENT                 # existing theme kept
    assert CONFIG["theme"]["sidebar"]["backgroundColor"] == ui_theme.SIDEBAR_BACKGROUND


# --- KPI tones and keys ------------------------------------------------------------------------


@pytest.mark.parametrize("label,value,tone", [
    ("Analysis status", "Complete", "success"),
    ("Analysis status", "Partial — KDE failed", "warning"),
    ("Analysis status", "Failed", "error"),
    ("Analysis status", NOT_RUN, "info"),
    ("Validation status", "Ready", "success"),
    ("Validation status", "Ready with rejections", "warning"),
    ("Validation status", "Unusable", "error"),
    ("Clusters", "2", None),
    ("Noise share", NOT_RUN, None),
])
def test_kpi_tone(label, value, tone):
    assert kpi_tone(label, value) == tone


def test_kpi_keys_are_stable_and_carry_the_tone():
    assert kpi_key("Analysis status", "Complete") == "kpi_badge_success_analysis_status"
    assert kpi_key("Noise share", "8.6%") == "kpi_card_noise_share"
    assert kpi_key("Rows in file", "35") == "kpi_card_rows_in_file"


def test_kpi_values_and_labels_unchanged_in_the_app(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "HISTORY_DB_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(dashboard, "HISTORY_REPORTS_DIR", tmp_path / "reports")
    points = [(23.0200 + 0.0001 * i, 72.5700) for i in range(12)] + \
             [(23.0650 + 0.0001 * i, 72.5800) for i in range(6)] + [(23.1000, 72.6500)]
    raw = pd.DataFrame({"incident_id": [f"P{i}" for i in range(len(points))],
                        "latitude": [repr(p[0]) for p in points], "longitude": [repr(p[1]) for p in points]}, dtype=str)
    at = AppTest.from_string(SCRIPT.replace("PAGE", repr("Summary")), default_timeout=120)
    at.session_state["dataset"] = validate_and_clean(raw, "s.csv")
    at.run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric} == {
        "Rows in file": "19", "Accepted incidents": "19", "Rejected": "0", "Analysis status": "Complete",
        "Clusters": "2", "Candidate hotspots": "1", "Noise incidents": "1 of 19", "Noise share": "5.3%"}


def test_status_badges_wrap_inside_cards_and_cards_top_align():
    """Long badge text wraps within the card; labels share one offset; 104 px card height kept."""
    css = ui_theme.SHELL_CSS
    assert ui_theme.KPI_CARD_MIN_HEIGHT_PX == 104 and "min-height: 104px" in css
    card_rule = next(rule for rule in css.splitlines() if rule.startswith('[class*="st-key-kpi_"] {'))
    assert "justify-content: flex-start" in card_rule
    assert "white-space: normal" in css and "max-width: 100%" in css and "overflow-wrap: break-word" in css
    assert ui_theme.BADGE_RADIUS_PX == 13 and "border-radius: 13px" in css and "999px" not in css
    assert f"font-size: {ui_theme.BADGE_VALUE_PX}px" in css and ui_theme.BADGE_VALUE_PX == 14
