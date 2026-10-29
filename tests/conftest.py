"""Shared fixtures. Synthetic frames only — clearly fake, never presented as real data."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def synthetic_raw_frame() -> pd.DataFrame:
    """Five synthetic rows: 3 valid, 1 missing latitude, 1 out-of-range longitude."""
    return pd.DataFrame(
        {
            "incident_id": ["T1", "T2", "T3", "T4", "T5"],
            "latitude": [23.02, 23.03, 23.04, None, 23.05],
            "longitude": [72.57, 72.58, 72.59, 72.60, 200.0],
            "severity": ["minor", "major", "minor", "fatal", "minor"],
        }
    )
