"""Design system: colour, typography and chart tokens for the dashboard.

Single source of truth for UI styling. `.streamlit/config.toml` applies the
same values to Streamlit's native theme, and tests check that the two agree.
This module has no Streamlit import (only dashboard.py may import Streamlit)
and no behaviour: it only defines constants and a Plotly template.

Analytical colours (cluster palette, noise, KDE density, threshold layer) are
NOT defined here; they stay in map_visualization.py and are only referenced.
"""

from __future__ import annotations

import plotly.graph_objects as go

from modules.map_visualization import CLUSTER_PALETTE

# --- Colour palette (approved Stage 10B design) ---------------------------------
BACKGROUND = "#F6F7F9"
SURFACE = "#FFFFFF"
BORDER = "#E2E6EC"
TEXT_PRIMARY = "#1A2433"
TEXT_SECONDARY = "#5A6677"
ACCENT = "#0E6E8C"
ACCENT_HOVER = "#0A5468"          # no native Streamlit option; reserved for later phases
SIDEBAR_BACKGROUND = "#102233"
SIDEBAR_TEXT = "#E6EDF5"
SUCCESS = "#2F855A"
WARNING = "#B7791F"
ERROR = "#C53030"
INFO = "#2B6CB0"

# Derived shades (not new brand colours): needed so widgets and lines stay
# legible on the dark sidebar and charts keep subtle gridlines.
SIDEBAR_SURFACE = "#1B3349"       # widget background inside the navy sidebar
SIDEBAR_BORDER = "#2C4862"
CHART_GRID = "#EEF1F4"
CHART_SECONDARY = "#B5BFCC"       # second series in single-colour charts

# --- Typography -------------------------------------------------------------------------
FONT_FAMILY = "Inter"
# Intended fallbacks. Plotly charts use this full stack; Streamlit's own text keeps
# only the first family and falls back to its bundled Source Sans (works offline).
FONT_FALLBACKS = ("Segoe UI", "system-ui", "sans-serif")
FONT_STACK = ", ".join((FONT_FAMILY, *FONT_FALLBACKS))
FONT_CSS_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap"
BODY_SIZE_PX = 15
PAGE_HEADING_PX = 28              # pages use st.header (h2) today; h1 matches it
SECTION_HEADING_PX = 20           # st.subheader (h3)
CARD_HEADING_PX = 16              # h4
CAPTION_PX = 13                   # Streamlit captions are 0.875rem = 13.1px at a 15px base
HEADING_WEIGHT = 600
METRIC_VALUE_PX = 28

# --- Surfaces, spacing and badges (Stage 10B Phase 4.2) ----------------------------------
def _mix(colour: str, other: str, share: float) -> str:
    """Hex colour that is `share` of `colour` and the rest `other` (sRGB channel mix)."""
    a = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * share + y * (1 - share)):02X}" for x, y in zip(a, b))


SHADOW_CARD = "0 1px 2px rgba(16, 34, 51, 0.06), 0 1px 3px rgba(16, 34, 51, 0.08)"
RADIUS_CARD_PX = 10
SPACING_PX = (4, 8, 12, 16, 24, 32)
SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL, SPACE_2XL = SPACING_PX
KPI_LABEL_PX = 13
KPI_LABEL_WEIGHT = 500
BADGE_VALUE_PX = 15
BADGE_RADIUS_PX = 13              # full pill on one line (26 px tall); stays tidy when text wraps
KPI_CARD_MIN_HEIGHT_PX = 104
# Status badges: background = 12% tint of the status colour on white; text = the same
# colour darkened to 70% so it stays >= 4.5:1 on the tint (the plain tokens do not).
BADGE_TINT = 0.12
BADGE_TEXT_SHADE = 0.70
STATUS_COLOURS = {"success": SUCCESS, "warning": WARNING, "error": ERROR, "info": INFO}
BADGE_BACKGROUND = {tone: _mix(colour, SURFACE, BADGE_TINT) for tone, colour in STATUS_COLOURS.items()}
BADGE_TEXT = {tone: _mix(colour, "#000000", BADGE_TEXT_SHADE) for tone, colour in STATUS_COLOURS.items()}
# Main-area gap under the header; mirrored by theme.paddingTop in .streamlit/config.toml
# (Streamlit's default is 6rem).
MAIN_PADDING_TOP = "2rem"
# The sidebar would inherit MAIN_PADDING_TOP; this keeps its original position.
SIDEBAR_PADDING_TOP = "1rem"

# --- Application shell (Stage 10B Phase 2) ----------------------------------------------
# Streamlit marks the current page link only through internal styling, so app.py wraps
# that one link in st.container(key=NAV_ACTIVE_KEY); keyed containers get the stable
# CSS class "st-key-<key>". All custom CSS lives in SHELL_CSS: static, built from the tokens
# above, never from user data.
NAV_ACTIVE_KEY = "nav_active"
# KPI cards (Phase 4.2): dashboard.kpi_strip wraps each st.metric in a keyed container
# whose key starts with KPI_KEY_PREFIX; status cards add "badge_<tone>_". Rules are
# scoped to those keyed containers; inside them they use st.metric's data-testid
# hooks for the label and value only.
KPI_KEY_PREFIX = "kpi_"
_KPI = f'[class*="st-key-{KPI_KEY_PREFIX}"]'
_KPI_CSS = (
    f"{_KPI} {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_CARD_PX}px; "
    f"box-shadow: {SHADOW_CARD}; padding: {SPACE_XL}px {SPACE_LG}px {SPACE_XS}px; "
    f"min-height: {KPI_CARD_MIN_HEIGHT_PX}px; justify-content: flex-start; }}\n"
    f'{_KPI} [data-testid="stMetricLabel"] p {{ font-size: {KPI_LABEL_PX}px; font-weight: {KPI_LABEL_WEIGHT}; '
    f"color: {TEXT_SECONDARY}; }}\n"
    f'{_KPI} [data-testid="stMetricValue"] {{ font-size: {METRIC_VALUE_PX}px; font-weight: {HEADING_WEIGHT}; '
    f"color: {TEXT_PRIMARY}; line-height: 1.2; }}\n"
    f'[class*="st-key-{KPI_KEY_PREFIX}badge_"] [data-testid="stMetricValue"], '
    f'[class*="st-key-{KPI_KEY_PREFIX}badge_"] [data-testid="stMetricValue"] * {{ '
    f"max-width: 100%; box-sizing: border-box; white-space: normal; overflow: visible; text-overflow: clip; "
    f"overflow-wrap: break-word; }}\n"
    + "".join(
        f'[class*="st-key-{KPI_KEY_PREFIX}badge_{tone}_"] [data-testid="stMetricValue"] {{ '
        f"display: inline-block; width: auto; font-size: {BADGE_VALUE_PX}px; font-weight: {HEADING_WEIGHT}; "
        f"background-color: {BADGE_BACKGROUND[tone]}; color: {BADGE_TEXT[tone]}; "
        f"padding: {SPACE_XS}px {SPACE_MD}px; margin-top: {SPACE_XS}px; border-radius: {BADGE_RADIUS_PX}px; }}\n"
        for tone in STATUS_COLOURS
    )
)
SHELL_CSS = (
    f".st-key-{NAV_ACTIVE_KEY} a {{ background-color: {ACCENT} !important; }}\n"
    f".st-key-{NAV_ACTIVE_KEY} a span, .st-key-{NAV_ACTIVE_KEY} a p {{ color: {SURFACE} !important; }}\n"
    + _KPI_CSS
)

# --- Charts ----------------------------------------------------------------------------
# Single-series charts use the accent; categorical charts reuse the map's cluster
# palette so a cluster has the same colour on the map and in a chart.
CHART_COLORWAY = (ACCENT, CHART_SECONDARY, *CLUSTER_PALETTE)
CHART_HEIGHT_PX = 320


def plotly_template() -> go.layout.Template:
    """Plotly template matching the design system (fonts, colours, light grid).

    Returns a new object each call so callers can't mutate a shared instance.
    It is not registered globally: pages opt in with
    `fig.update_layout(template=plotly_template())`.
    """
    axis = {"gridcolor": CHART_GRID, "linecolor": BORDER, "zerolinecolor": BORDER,
            "tickfont": {"color": TEXT_SECONDARY}, "title": {"font": {"color": TEXT_SECONDARY}}}
    return go.layout.Template(layout={
        "font": {"family": FONT_STACK, "size": CAPTION_PX, "color": TEXT_PRIMARY},
        "colorway": list(CHART_COLORWAY),
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "margin": {"l": 48, "r": 16, "t": 40, "b": 40},
        "height": CHART_HEIGHT_PX,
        "xaxis": axis,
        "yaxis": axis,
        "legend": {"orientation": "h", "y": 1.08, "x": 0, "font": {"color": TEXT_SECONDARY}},
        "hoverlabel": {"bgcolor": SURFACE, "bordercolor": BORDER, "font": {"family": FONT_STACK, "color": TEXT_PRIMARY}},
        "title": {"font": {"size": CARD_HEADING_PX, "color": TEXT_PRIMARY}, "x": 0, "xanchor": "left"},
    })
