"""Shared fixtures. The synthetic sample is generated once per test session into a temp dir."""

from __future__ import annotations

from pathlib import Path

import pytest

from mobilityops.sample import SampleFiles, SampleSpec, generate_sample


@pytest.fixture(scope="session")
def sample_files(tmp_path_factory: pytest.TempPathFactory) -> SampleFiles:
    """TEST / SYNTHETIC DATA: the default 12-zone, 56-day sample."""
    return generate_sample(tmp_path_factory.mktemp("sample"), SampleSpec())


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"
