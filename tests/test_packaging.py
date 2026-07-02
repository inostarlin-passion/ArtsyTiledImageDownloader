from __future__ import annotations

from pathlib import Path

import tomllib


def test_pyproject_declares_pypi_metadata(project_root: Path) -> None:
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text())
    project = pyproject["project"]

    assert project["name"] == "artsy-tiled-image-downloader"
    assert project["readme"] == "README.md"
    assert project["license"] == "MIT"
    assert "LICENSE" in project["license-files"]
    assert "artsy-downloader" in project["scripts"]
    assert project["urls"]["Repository"].startswith("https://github.com/")
