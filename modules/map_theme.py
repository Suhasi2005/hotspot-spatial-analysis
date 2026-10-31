"""Dark presentation for Folium maps. Rendering only: no data, no calculations.

Maps run inside their own iframe, so the application's CSS cannot reach them; these
elements add the styling from inside the map. They use a script because st_folium
keeps a map's scripts but not everything in its page header.

Basemap: the free OpenStreetMap tiles the app already uses, darkened in the browser
with a CSS filter on the tile layer only, so markers and overlays keep their colours.
It needs no API key, new service or dependency, and keeps the OpenStreetMap
attribution. CARTO's dark tiles are not used: they now show an "API KEY REQUIRED"
watermark unless a key is supplied, and a key does not belong in a public repository.

The colours mirror ui_theme, which cannot be imported here because it imports
map_visualization. tests/test_clusters_page.py checks that they agree.
"""

from __future__ import annotations

from branca.element import MacroElement
from jinja2 import Template

MAP_BACKGROUND = "#071321"
MAP_PANEL = "#102438"
MAP_BORDER = "#2A4A66"
MAP_TEXT = "#EAF2FA"
MAP_TEXT_MUTED = "#9BB0C5"
MAP_ACCENT = "#08B8D4"
TILE_FILTER = "invert(1) hue-rotate(195deg) brightness(0.72) contrast(1.15) saturate(0.55)"
LEGEND_CLASS = "hs-map-legend"
CHIP_CLASS = "hs-map-chip"

DARK_MAP_CSS = f"""
.leaflet-container {{ background: {MAP_BACKGROUND}; font-family: Inter, 'Segoe UI', system-ui, sans-serif; }}
.leaflet-tile-pane {{ filter: {TILE_FILTER}; }}
.leaflet-bar a, .leaflet-control-layers {{ background: {MAP_PANEL}; color: {MAP_TEXT}; border-color: {MAP_BORDER}; }}
.leaflet-bar a:hover {{ background: {MAP_BORDER}; color: {MAP_TEXT}; }}
.leaflet-bar a.leaflet-disabled {{ background: {MAP_PANEL}; color: {MAP_TEXT_MUTED}; }}
.leaflet-bar {{ border: 1px solid {MAP_BORDER}; box-shadow: none; }}
.leaflet-control-layers {{ border: 1px solid {MAP_BORDER}; border-radius: 8px; box-shadow: none; font-size: 12px; }}
.leaflet-control-layers-toggle {{ filter: invert(1) brightness(1.4); }}
.leaflet-control-layers-separator {{ border-top-color: {MAP_BORDER}; }}
.leaflet-control-attribution {{ background: rgba(16, 36, 56, 0.85) !important; color: {MAP_TEXT_MUTED}; font-size: 11px; }}
.leaflet-control-attribution a {{ color: {MAP_ACCENT}; }}
.leaflet-control-scale-line {{ background: rgba(16, 36, 56, 0.85); color: {MAP_TEXT}; border-color: {MAP_TEXT_MUTED}; font-size: 11px; }}
.leaflet-popup-content-wrapper, .leaflet-popup-tip {{ background: {MAP_PANEL}; color: {MAP_TEXT}; }}
.leaflet-popup-content-wrapper {{ border: 1px solid {MAP_BORDER}; border-radius: 8px; }}
.leaflet-popup-content {{ font-size: 12px; line-height: 1.5; }}
.leaflet-container a.leaflet-popup-close-button {{ color: {MAP_TEXT_MUTED}; }}
.leaflet-tooltip {{ background: {MAP_PANEL}; color: {MAP_TEXT}; border: 1px solid {MAP_BORDER}; box-shadow: none; font-size: 12px; }}
.leaflet-tooltip-left::before {{ border-left-color: {MAP_BORDER}; }}
.leaflet-tooltip-right::before {{ border-right-color: {MAP_BORDER}; }}
.{LEGEND_CLASS} {{ background: {MAP_PANEL}; color: {MAP_TEXT}; border: 1px solid {MAP_BORDER}; border-radius: 8px;
  padding: 8px 10px; font-size: 12px; line-height: 1.5; pointer-events: none; }}
.{LEGEND_CLASS} b {{ display: block; color: {MAP_TEXT_MUTED}; font-weight: 500; }}
.{LEGEND_CLASS} i {{ display: inline-block; width: 10px; height: 10px; margin-right: 6px; border-radius: 50%;
  box-sizing: border-box; }}
.{CHIP_CLASS} {{ display: inline-block; transform: translate(-50%, -150%); padding: 1px 7px; white-space: nowrap;
  background: {MAP_PANEL}; color: {MAP_TEXT}; border: 1px solid; border-radius: 10px; font-size: 11px;
  font-weight: 600; pointer-events: none; }}
"""


class DarkMapStyle(MacroElement):
    """Applies DARK_MAP_CSS inside the map's own document."""

    _template = Template("""
{% macro script(this, kwargs) %}
(function () {
    var style = document.createElement("style");
    style.textContent = {{ this.css|tojson }};
    document.head.appendChild(style);
})();
{% endmacro %}
""")

    def __init__(self):
        super().__init__()
        self._name = "DarkMapStyle"
        self.css = DARK_MAP_CSS


class MapLegend(MacroElement):
    """A static Leaflet control holding legend HTML built from numbers and fixed text.

    Leaflet draws controls above popups, so the legend steps aside while one is open.
    """

    _template = Template("""
{% macro script(this, kwargs) %}
(function () {
    var map = {{ this._parent.get_name() }};
    var legend = L.control({position: "topleft"});
    legend.onAdd = function () {
        var box = L.DomUtil.create("div", {{ this.css_class|tojson }});
        box.innerHTML = {{ this.body|tojson }};
        map.on("popupopen", function () { box.style.visibility = "hidden"; });
        map.on("popupclose", function () { box.style.visibility = "visible"; });
        return box;
    };
    legend.addTo(map);
})();
{% endmacro %}
""")

    def __init__(self, body: str):
        super().__init__()
        self._name = "MapLegend"
        self.body = body
        self.css_class = LEGEND_CLASS
