"""Design-system tests: approved tokens, Streamlit theme agreement, Plotly template, palettes."""

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import plotly.graph_objects as go
import pytest

from modules import map_visualization, ui_theme

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".streamlit" / "config.toml"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

APPROVED = {
    "BACKGROUND": "#F6F7F9", "SURFACE": "#FFFFFF", "BORDER": "#E2E6EC",
    "TEXT_PRIMARY": "#1A2433", "TEXT_SECONDARY": "#5A6677",
    "ACCENT": "#0E6E8C", "ACCENT_HOVER": "#0A5468",
    "SIDEBAR_BACKGROUND": "#102233", "SIDEBAR_TEXT": "#E6EDF5",
    "SUCCESS": "#2F855A", "WARNING": "#B7791F", "ERROR": "#C53030", "INFO": "#2B6CB0",
}


def _theme():
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]


def _contrast(fg: str, bg: str) -> float:
    def luminance(hex_colour):
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    light, dark = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# --- tokens -----------------------------------------------------------------------------


@pytest.mark.parametrize("name,value", APPROVED.items())
def test_colour_constants_match_the_approved_palette(name, value):
    assert getattr(ui_theme, name) == value


def test_every_colour_constant_is_a_six_digit_hex():
    for name in [*APPROVED, "SIDEBAR_SURFACE", "SIDEBAR_BORDER", "CHART_GRID", "CHART_SECONDARY"]:
        assert HEX.match(getattr(ui_theme, name)), name


def test_typography_tokens():
    assert ui_theme.FONT_FAMILY == "Inter"
    assert ui_theme.FONT_STACK.startswith("Inter, Segoe UI") and ui_theme.FONT_STACK.endswith("sans-serif")
    assert (ui_theme.BODY_SIZE_PX, ui_theme.PAGE_HEADING_PX, ui_theme.SECTION_HEADING_PX,
            ui_theme.CARD_HEADING_PX, ui_theme.CAPTION_PX, ui_theme.HEADING_WEIGHT) == (15, 28, 20, 16, 13, 600)
    assert round(0.875 * ui_theme.BODY_SIZE_PX) == ui_theme.CAPTION_PX    # Streamlit caption = 0.875rem


@pytest.mark.parametrize("fg,bg,minimum", [
    ("TEXT_PRIMARY", "BACKGROUND", 7.0), ("TEXT_PRIMARY", "SURFACE", 7.0),
    ("TEXT_SECONDARY", "BACKGROUND", 4.5), ("TEXT_SECONDARY", "SURFACE", 4.5),
    ("SURFACE", "ACCENT", 4.5),                                   # button text on the accent
    ("ACCENT", "SURFACE", 4.5),                                   # links on white
    ("SIDEBAR_TEXT", "SIDEBAR_BACKGROUND", 7.0), ("SIDEBAR_TEXT", "SIDEBAR_SURFACE", 7.0),
    ("SURFACE", "ERROR", 4.5), ("SURFACE", "SUCCESS", 4.5), ("SURFACE", "INFO", 4.5),
])
def test_text_colour_pairs_meet_wcag_contrast(fg, bg, minimum):
    assert _contrast(getattr(ui_theme, fg), getattr(ui_theme, bg)) >= minimum


# --- Streamlit theme agrees with the tokens ----------------------------------------------------


def test_streamlit_theme_uses_the_design_tokens():
    theme = _theme()
    assert theme["base"] == "light"
    assert (theme["primaryColor"], theme["backgroundColor"], theme["secondaryBackgroundColor"],
            theme["textColor"], theme["borderColor"], theme["linkColor"]) == (
        ui_theme.ACCENT, ui_theme.BACKGROUND, ui_theme.SURFACE, ui_theme.TEXT_PRIMARY,
        ui_theme.BORDER, ui_theme.ACCENT)
    assert (theme["greenColor"], theme["yellowColor"], theme["redColor"], theme["blueColor"]) == (
        ui_theme.SUCCESS, ui_theme.WARNING, ui_theme.ERROR, ui_theme.INFO)
    assert theme["showWidgetBorder"] is True and theme["baseRadius"] == "6px"


def test_streamlit_theme_typography():
    theme = _theme()
    for key in ("font", "headingFont"):
        families = [part.split(":")[0].strip() for part in theme[key].split(", ")]
        assert families == [ui_theme.FONT_FAMILY, *ui_theme.FONT_FALLBACKS]
        assert ui_theme.FONT_CSS_URL in theme[key]
    assert theme["baseFontSize"] == ui_theme.BODY_SIZE_PX
    assert theme["headingFontSizes"] == [f"{ui_theme.PAGE_HEADING_PX}px", f"{ui_theme.PAGE_HEADING_PX}px",
                                         f"{ui_theme.SECTION_HEADING_PX}px", f"{ui_theme.CARD_HEADING_PX}px"]
    assert theme["headingFontWeights"] == [ui_theme.HEADING_WEIGHT] * 4
    assert theme["metricValueFontSize"] == f"{ui_theme.METRIC_VALUE_PX}px"


def test_streamlit_sidebar_theme():
    sidebar = _theme()["sidebar"]
    assert (sidebar["backgroundColor"], sidebar["textColor"], sidebar["secondaryBackgroundColor"],
            sidebar["borderColor"]) == (ui_theme.SIDEBAR_BACKGROUND, ui_theme.SIDEBAR_TEXT,
                                        ui_theme.SIDEBAR_SURFACE, ui_theme.SIDEBAR_BORDER)


def test_streamlit_chart_palette_is_the_cluster_palette():
    assert tuple(_theme()["chartCategoricalColors"]) == map_visualization.CLUSTER_PALETTE


def test_streamlit_itself_reads_the_theme():
    """Run Streamlit's own config loader in the project folder (no server is started)."""
    code = ("from streamlit import config; "
            "print(config.get_option('theme.primaryColor'), config.get_option('theme.sidebar.backgroundColor'), "
            "config.get_option('theme.baseFontSize'))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == [ui_theme.ACCENT, ui_theme.SIDEBAR_BACKGROUND, str(ui_theme.BODY_SIZE_PX)]


# --- Plotly template ------------------------------------------------------------------------------


def test_plotly_template_is_valid_and_uses_the_tokens():
    template = ui_theme.plotly_template()
    assert isinstance(template, go.layout.Template)
    layout = template.layout
    assert layout.font.family == ui_theme.FONT_STACK and layout.font.color == ui_theme.TEXT_PRIMARY
    assert list(layout.colorway) == list(ui_theme.CHART_COLORWAY)
    assert layout.colorway[0] == ui_theme.ACCENT
    assert layout.paper_bgcolor == layout.plot_bgcolor == ui_theme.SURFACE
    assert layout.xaxis.gridcolor == layout.yaxis.gridcolor == ui_theme.CHART_GRID
    fig = go.Figure(go.Bar(x=["a", "b"], y=[1, 2]))
    fig.update_layout(template=template)
    assert fig.to_plotly_json()["layout"]["template"]["layout"]["font"]["family"] == ui_theme.FONT_STACK


def test_plotly_template_is_a_fresh_object_and_not_registered_globally():
    import plotly.io as pio

    default_before = pio.templates.default        # Streamlit may already have set its own default
    registered_before = set(pio.templates)
    first, second = ui_theme.plotly_template(), ui_theme.plotly_template()
    assert first is not second
    assert pio.templates.default == default_before and set(pio.templates) == registered_before


# --- boundaries ---------------------------------------------------------------------------------------


def test_ui_theme_does_not_import_streamlit():
    tree = ast.parse((ROOT / "modules" / "ui_theme.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "streamlit" not in imported


def test_analytical_palettes_are_unchanged():
    assert map_visualization.CLUSTER_PALETTE == (
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#bcbd22", "#17becf", "#7f7f7f")
    assert map_visualization.NOISE_COLOR == "#616161"
    assert map_visualization.DENSITY_COLORS == ("#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026")
    assert map_visualization.THRESHOLD_RGBA == (49, 54, 149, 110)
    assert map_visualization.POINT_STYLE["fill_color"] == "#2e86c1"
    assert ui_theme.CHART_COLORWAY[2:] == map_visualization.CLUSTER_PALETTE   # referenced, not redefined
