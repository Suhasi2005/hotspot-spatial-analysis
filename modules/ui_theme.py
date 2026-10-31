"""Design system: colour, typography and chart tokens for the dashboard.

Single source of truth for UI styling. `.streamlit/config.toml` applies the
same values to Streamlit's native theme, and tests check that the two agree.
This module has no Streamlit import (only dashboard.py and ui_components.py may)
and no behaviour: it only defines constants and a Plotly template.

Analytical colours (cluster palette, noise, KDE density, threshold layer) are
NOT defined here; they stay in map_visualization.py and are only referenced.
"""

from __future__ import annotations

import plotly.graph_objects as go

from modules.map_visualization import CLUSTER_PALETTE

# --- Colour palette (approved dark geospatial design, Stage 1) ---------------------------
BACKGROUND = "#071321"
SECONDARY_BACKGROUND = "#0D1F30"
SURFACE = "#102438"               # cards and panels
SURFACE_ELEVATED = "#142B40"
BORDER = "#1E3A52"                # card edges
BORDER_STRONG = "#2A4A66"         # widget edges
TEXT_PRIMARY = "#EAF2FA"
TEXT_SECONDARY = "#9BB0C5"
ACCENT = "#08B8D4"
ACCENT_HOVER = "#2CCDE6"
ACCENT_BLUE = "#2878E5"           # fills only: below 4.5:1 as text on cards
ON_ACCENT = "#061A24"             # text on the accent; white is only 2.4:1
SIDEBAR_BACKGROUND = "#091827"
SIDEBAR_TEXT = "#EAF2FA"
SUCCESS = "#20C997"
WARNING = "#E8B44A"
ERROR = "#F06464"
INFO = "#5CB0F5"

# Derived shades (not new brand colours).
SIDEBAR_SURFACE = "#102438"       # widget background inside the sidebar
SIDEBAR_BORDER = "#1E3A52"
CHART_GRID = "#1E3A52"
CHART_SECONDARY = "#5F7F9C"       # second series in single-colour charts

# --- Typography -------------------------------------------------------------------------
FONT_FAMILY = "Inter"
# Intended fallbacks. Plotly charts use this full stack; Streamlit's own text keeps
# only the first family and falls back to its bundled Source Sans (works offline).
FONT_FALLBACKS = ("Segoe UI", "system-ui", "sans-serif")
FONT_STACK = ", ".join((FONT_FAMILY, *FONT_FALLBACKS))
FONT_CSS_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap"
BODY_SIZE_PX = 14
PAGE_HEADING_PX = 26              # pages use st.header (h2) today; h1 matches it
SECTION_HEADING_PX = 18           # st.subheader (h3)
CARD_HEADING_PX = 14              # h4
CAPTION_PX = 12                   # Streamlit captions are 0.875rem = 12.25px at a 14px base
HEADING_WEIGHT = 600
METRIC_VALUE_PX = 28

# --- Surfaces, spacing and badges (Stage 10B Phase 4.2) ----------------------------------
def _mix(colour: str, other: str, share: float) -> str:
    """Hex colour that is `share` of `colour` and the rest `other` (sRGB channel mix)."""
    a = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * share + y * (1 - share)):02X}" for x, y in zip(a, b))


SHADOW_CARD = "0 1px 2px rgba(2, 8, 16, 0.4), 0 4px 12px rgba(2, 8, 16, 0.3)"
RADIUS_CARD_PX = 10
SPACING_PX = (4, 8, 12, 16, 24, 32)
SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL, SPACE_2XL = SPACING_PX
KPI_LABEL_PX = 12
KPI_LABEL_WEIGHT = 500
BADGE_VALUE_PX = 14
BADGE_RADIUS_PX = 13              # full pill on one line (26 px tall); stays tidy when text wraps
KPI_CARD_MIN_HEIGHT_PX = 104
# Status badges: background = 16% tint of the status colour on the card; text = the same
# colour lifted towards the primary text so it stays >= 4.5:1 on the tint.
BADGE_TINT = 0.16
BADGE_TEXT_SHARE = 0.70
STATUS_COLOURS = {"success": SUCCESS, "warning": WARNING, "error": ERROR, "info": INFO}
BADGE_BACKGROUND = {tone: _mix(colour, SURFACE, BADGE_TINT) for tone, colour in STATUS_COLOURS.items()}
BADGE_TEXT = {tone: _mix(colour, TEXT_PRIMARY, BADGE_TEXT_SHARE) for tone, colour in STATUS_COLOURS.items()}
# Tinted, not filled, so the active page text keeps its full contrast.
NAV_ACTIVE_BACKGROUND = _mix(ACCENT, SIDEBAR_BACKGROUND, 0.18)
# Main-area gap under the header; mirrored by theme.paddingTop in .streamlit/config.toml
# (Streamlit's default is 6rem).
MAIN_PADDING_TOP = "2rem"
# The sidebar would inherit MAIN_PADDING_TOP; this keeps its original position.
SIDEBAR_PADDING_TOP = "1rem"

# --- Application shell (Stage 10B Phase 2) ----------------------------------------------
# Streamlit marks the current page link only through internal styling, so app_shell wraps
# that one link in st.container(key=NAV_ACTIVE_KEY); keyed containers get the stable
# CSS class "st-key-<key>". All custom CSS lives in SHELL_CSS: static, built from the tokens
# above, never from user data.
NAV_ACTIVE_KEY = "nav_active"
MOBILE_NAV_KEY = "mobile_nav"
MOBILE_NAV_ACTIVE_KEY = "mobile_nav_active"
FILTERS_KEY = "display_filters"
MOBILE_BREAKPOINT_PX = 768         # Streamlit hides the sidebar below this width
# KPI cards (Phase 4.2): ui_components.kpi_strip wraps each st.metric in a keyed container
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
# Panels and empty-state cards share one style. The Summary page's KPI grid wraps four
# across on desktop and two on phones.
SUMMARY_KPI_KEY = "summary_kpis"
DATA_KPI_KEY = "data_kpis"
PANEL_PREFIX = "panel_"
EMPTY_STATE_PREFIX = "empty_state_"
_EMPTY_LINK = f'[class*="st-key-{EMPTY_STATE_PREFIX}"] a'
KPI_GRID_MIN_CARD_PX = 160
_SUMMARY_CSS = (
    f".st-key-{SUMMARY_KPI_KEY} > *, .st-key-{DATA_KPI_KEY} > * {{ flex: 1 1 calc(25% - {SPACE_LG}px); max-width: 100%; "
    f"min-width: {KPI_GRID_MIN_CARD_PX}px; }}\n"
    f'[class*="st-key-{PANEL_PREFIX}"], '
    f'[class*="st-key-{EMPTY_STATE_PREFIX}"] {{ background-color: {SURFACE}; border: 1px solid {BORDER}; '
    f"border-radius: {RADIUS_CARD_PX}px; box-shadow: {SHADOW_CARD}; padding: {SPACE_LG}px; }}\n"
    f"{_EMPTY_LINK} {{ background-color: {ACCENT} !important; padding: {SPACE_XS}px {SPACE_MD}px; }}\n"
    f"{_EMPTY_LINK}:hover {{ background-color: {ACCENT_HOVER} !important; }}\n"
    f"{_EMPTY_LINK} span, {_EMPTY_LINK} p {{ color: {ON_ACCENT} !important; }}\n"
    f'[class*="st-key-{PANEL_PREFIX}"] [data-testid="stBaseButton-primary"] {{ background-color: {ACCENT}; '
    f"border-color: {ACCENT}; }}\n"
    f'[class*="st-key-{PANEL_PREFIX}"] [data-testid="stBaseButton-primary"]:hover {{ '
    f"background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}\n"
    f'[class*="st-key-{PANEL_PREFIX}"] [data-testid="stBaseButton-primary"] p {{ color: {ON_ACCENT}; }}\n'
)
# Data page: a prominent drop area, and a slimmer panel for the one-line dataset bar.
_DATA_CSS = (
    f'.st-key-{PANEL_PREFIX}data_source [data-testid="stFileUploaderDropzone"] {{ min-height: 120px; display: flex; '
    f"flex-direction: column; align-items: center; justify-content: center; gap: {SPACE_SM}px; "
    f"background-color: {SECONDARY_BACKGROUND}; border: 1px dashed {ACCENT}; border-radius: {RADIUS_CARD_PX}px; }}\n"
    f".st-key-{PANEL_PREFIX}dataset_bar {{ padding: {SPACE_SM}px {SPACE_LG}px; }}\n"
)
# Phone page bar: five equal tabs, icon above label, so every page shows without scrolling.
_MOBILE_NAV = f".st-key-{MOBILE_NAV_KEY}"
_MOBILE_ACTIVE = f".st-key-{MOBILE_NAV_ACTIVE_KEY}"
_NAV_CSS = (
    f".st-key-{NAV_ACTIVE_KEY} a, {_MOBILE_ACTIVE} a {{ background-color: {NAV_ACTIVE_BACKGROUND} !important; "
    f"box-shadow: inset 3px 0 0 {ACCENT}; }}\n"
    f".st-key-{NAV_ACTIVE_KEY} a span, .st-key-{NAV_ACTIVE_KEY} a p, {_MOBILE_ACTIVE} a span, {_MOBILE_ACTIVE} a p "
    f"{{ color: {TEXT_PRIMARY} !important; font-weight: {HEADING_WEIGHT}; }}\n"
    f"{_MOBILE_NAV} {{ flex-wrap: nowrap; gap: {SPACE_XS}px; padding: {SPACE_XS}px; background-color: {SIDEBAR_BACKGROUND}; "
    f"border: 1px solid {BORDER}; border-radius: {RADIUS_CARD_PX}px; }}\n"
    f"{_MOBILE_NAV} > * {{ flex: 1 1 0; min-width: 0; }}\n"
    f"{_MOBILE_NAV} div {{ width: 100%; max-width: 100%; }}\n"
    f"{_MOBILE_NAV} a {{ flex-direction: column; align-items: center; justify-content: center; gap: 2px; width: 100%; "
    f"min-height: 48px; "
    f"padding: {SPACE_XS}px 2px; }}\n"
    f"{_MOBILE_NAV} a p {{ font-size: 11px; line-height: 1.2; white-space: nowrap; }}\n"
    f"@media (min-width: {MOBILE_BREAKPOINT_PX}px) {{ {_MOBILE_NAV} {{ display: none; }} }}\n"
    # Multiselect chips use the primary colour; Streamlit's white text on it is only 2.4:1.
    f'.st-key-{FILTERS_KEY} [data-testid="stMultiSelectTagsContainer"] span {{ '
    f"color: {ON_ACCENT} !important; }}\n"
)
SHELL_CSS = (
    _NAV_CSS
    + _KPI_CSS
    + _SUMMARY_CSS
    + _DATA_CSS
)

# --- Charts ----------------------------------------------------------------------------
# Single-series charts use the accent; categorical charts reuse the map's cluster
# palette so a cluster has the same colour on the map and in a chart.
CHART_COLORWAY = (ACCENT, CHART_SECONDARY, *CLUSTER_PALETTE)
CHART_HEIGHT_PX = 320


def plotly_template() -> go.layout.Template:
    """Plotly template matching the design system (fonts, colours, subtle grid).

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
        "hoverlabel": {"bgcolor": SURFACE_ELEVATED, "bordercolor": BORDER_STRONG, "font": {"family": FONT_STACK, "color": TEXT_PRIMARY}},
        "title": {"font": {"size": CARD_HEADING_PX, "color": TEXT_PRIMARY}, "x": 0, "xanchor": "left"},
    })


def bar_chart_layout(title: str, subtitle: str, xaxis_title: str) -> dict:
    """Layout for a single-series count chart: template, two-line title, no legend.

    The title sits on two short lines so it fits narrow charts. Pair it with
    `text=` values and `cliponaxis=False` on the bar trace; `margin.t` leaves room
    for the labels above the tallest bar.
    """
    return {
        "template": plotly_template(),
        "title": {"text": f"{title}<br><sup>{subtitle}</sup>", "x": 0, "xref": "paper", "xanchor": "left",
                  "y": 0.96, "yanchor": "top"},
        # Invisible outside ticks push the labels clear of the y-axis "0" on narrow charts.
        "xaxis": {"title": {"text": xaxis_title}, "ticks": "outside", "ticklen": 6, "tickcolor": SURFACE},
        "yaxis_title": "Incidents",
        "showlegend": False,
        "bargap": 0.35,
        "height": CHART_HEIGHT_PX + 40,
        "margin": {"l": 48, "r": 16, "t": 84, "b": 56},
        # Set here as well: Streamlit does not apply the template's paper colour.
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
    }
