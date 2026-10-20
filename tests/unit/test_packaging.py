"""The package version lives only in ``docsage.__version__``; pyproject reads it from there."""

import tomllib
from importlib.metadata import version
from pathlib import Path

from docsage import __version__

ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_reads_the_version_from_the_package():
    pyproject = _pyproject()

    assert "version" not in pyproject["project"]
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "docsage.__version__"
    }


def test_installed_metadata_matches_the_package_version():
    assert version("docsage") == __version__


def test_license_is_an_spdx_expression_shipped_with_the_package():
    project = _pyproject()["project"]

    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert (ROOT / "LICENSE").is_file()
