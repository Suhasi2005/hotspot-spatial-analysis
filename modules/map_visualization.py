"""Folium map builders. Owner: Member 4 (GIS Visualization).

Folium expects [lat, lon] order in DEGREES (GeoJSON is [lon, lat] — do not mix).
Builders return folium.Map objects and never call Streamlit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.contracts import CleanDataset, ClusterResult, DensityResult

if TYPE_CHECKING:
    import folium


def build_incident_map(dataset: CleanDataset) -> "folium.Map":
    """Point layer of all clean incidents. Stage 3."""
    raise NotImplementedError("Stage 3: map_visualization.build_incident_map")


def build_cluster_map(result: ClusterResult) -> "folium.Map":
    """Points coloured by cluster, noise greyed, candidate hotspots outlined. Stage 7."""
    raise NotImplementedError("Stage 7: map_visualization.build_cluster_map")


def build_density_map(result: DensityResult) -> "folium.Map":
    """KDE surface overlay, labelled as estimated density. Stage 7."""
    raise NotImplementedError("Stage 7: map_visualization.build_density_map")
