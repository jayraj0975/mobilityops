"""One project version, stated the same way everywhere it appears."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import mobilityops

REPO = Path(__file__).resolve().parents[2]


def test_the_python_package_web_app_and_lockfile_share_one_version() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
    web = json.loads((REPO / "apps/web/package.json").read_text())["version"]
    lock = json.loads((REPO / "apps/web/package-lock.json").read_text())
    assert (
        mobilityops.__version__
        == project
        == web
        == lock["version"]
        == lock["packages"][""]["version"]
    )


def test_the_changelog_describes_the_current_version() -> None:
    """A released version needs its own heading; unreleased work sits under 'Unreleased'."""
    text = (REPO / "CHANGELOG.md").read_text()
    headings = re.findall(r"^## (.+)$", text, flags=re.M)
    assert headings, "CHANGELOG.md has no version headings"
    assert headings[0] == "Unreleased" or headings[0].startswith(mobilityops.__version__), headings[
        0
    ]


def test_the_api_reports_the_package_version() -> None:
    from mobilityops.api.app import create_app
    from mobilityops.config import Settings

    app = create_app(Settings.from_env({"MOBILITYOPS_DATA_DIR": "/nonexistent"}))
    assert app.version == mobilityops.__version__
