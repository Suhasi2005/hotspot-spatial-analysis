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
