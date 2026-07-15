from __future__ import annotations

from pathlib import Path

import pytest
import tomllib

from artsy_tiled_image_downloader import __version__

pytestmark = pytest.mark.integration


def test_pyproject_declares_pypi_metadata(project_root: Path) -> None:
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text())
    project = pyproject["project"]

    assert project["name"] == "artsy-tiled-image-downloader"
    assert project["readme"] == "README.md"
    assert project["license"] == "MIT"
    assert "LICENSE" in project["license-files"]
    assert "artsy-downloader" in project["scripts"]
    assert project["urls"]["Repository"].startswith("https://github.com/")
    assert project["version"] == __version__


def test_readme_does_not_include_star_history(project_root: Path) -> None:
    readme = (project_root / "README.md").read_text()

    assert "Star History" not in readme
    assert "api.star-history.com" not in readme
