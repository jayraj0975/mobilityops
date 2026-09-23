"""Shared fixtures. The synthetic sample is generated once per test session into a temp dir."""

from __future__ import annotations

from pathlib import Path

import pytest

from mobilityops.config import Settings
from mobilityops.sample import SampleFiles, SampleSpec, generate_sample


@pytest.fixture(scope="session")
def sample_files(tmp_path_factory: pytest.TempPathFactory) -> SampleFiles:
    """TEST / SYNTHETIC DATA: the default 12-zone, 56-day sample."""
    return generate_sample(tmp_path_factory.mktemp("sample"), SampleSpec())


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
def sample_settings(sample_files: SampleFiles, tmp_path: Path) -> Settings:
    """A sample-mode Settings whose raw dir already holds the synthetic files."""
    s = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "data"), "MOBILITYOPS_MODE": "sample"}
    )
    s.ensure_dirs()
    for f in sample_files.directory.iterdir():
        (s.raw_dir / f.name).write_bytes(f.read_bytes())
    return s


def make_env(root: Path, files: SampleFiles) -> Settings:
    s = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(root / "data"), "MOBILITYOPS_MODE": "sample"}
    )
    s.ensure_dirs()
    for f in files.directory.iterdir():
        (s.raw_dir / f.name).write_bytes(f.read_bytes())
    return s


@pytest.fixture(scope="session")
def built_sample(sample_files: SampleFiles, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """The full pipeline run once on the synthetic sample; read-only tests share it."""
    from mobilityops.ingestion.pipeline import ingest_sample
    from mobilityops.pipeline import build_all

    settings = make_env(tmp_path_factory.mktemp("built"), sample_files)
    ingest_sample(settings)
    return settings, build_all(settings)
