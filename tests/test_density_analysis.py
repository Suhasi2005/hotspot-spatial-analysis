import pytest

from config.settings import KDEParams


def test_kde_params_reject_bad_quantile():
    with pytest.raises(ValueError):
        KDEParams(high_density_quantile=1.0)


def test_kde_params_reject_unsupported_kernel():
    with pytest.raises(ValueError):
        KDEParams(kernel="triweight")


@pytest.mark.skip(reason="Stage 5: run_kde not implemented")
def test_density_peaks_near_synthetic_concentration():
    """Density argmax should fall within one grid cell of a dense synthetic group."""
    pytest.fail("Test implementation pending")
