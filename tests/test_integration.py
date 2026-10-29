"""Structural integration checks: every module imports and exposes its contract."""

import ast
import importlib
from pathlib import Path

import pytest

MODULE_CONTRACTS = {
    "modules.data_manager": ["list_sample_datasets", "load_raw_dataset"],
    "modules.data_validator": ["validate_and_clean", "summarize_quality"],
    "modules.dbscan_analysis": ["run_dbscan", "metres_to_radians"],
    "modules.density_analysis": ["run_kde"],
    "modules.spatial_statistics": ["summarize", "haversine_m"],
    "modules.map_visualization": ["build_incident_map", "build_cluster_map", "build_density_map"],
    "modules.app_controller": ["run_analysis"],
    "modules.database": ["init_db", "save_run", "list_runs"],
    "modules.report_generator": ["export_csv", "export_pdf"],
}


@pytest.mark.parametrize("module_name,functions", MODULE_CONTRACTS.items())
def test_module_exposes_contract(module_name, functions):
    module = importlib.import_module(module_name)
    for fn in functions:
        assert callable(getattr(module, fn)), f"{module_name}.{fn} missing"


def _imports_streamlit(source: str) -> bool:
    """True if the code (not comments/strings) imports streamlit in any form."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "streamlit" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "streamlit":
            return True
    return False


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import streamlit as st", True),
        ("from streamlit import session_state", True),
        ("from streamlit.testing.v1 import AppTest", True),
        ("import streamlit_folium", False),
        ("# import streamlit\nx = 'import streamlit'", False),
    ],
)
def test_streamlit_import_detector(source, expected):
    assert _imports_streamlit(source) is expected


def test_analysis_modules_do_not_import_streamlit():
    """Only dashboard.py may import Streamlit; business logic stays UI-free."""
    modules_dir = Path(__file__).resolve().parent.parent / "modules"
    offenders = [
        p.name
        for p in modules_dir.glob("*.py")
        if p.name != "dashboard.py" and _imports_streamlit(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.skip(reason="Stage 8: run_analysis not implemented")
def test_end_to_end_pipeline_on_synthetic_data():
    """load -> validate -> DBSCAN -> KDE -> summary -> history row."""
    pytest.fail("Test implementation pending")
