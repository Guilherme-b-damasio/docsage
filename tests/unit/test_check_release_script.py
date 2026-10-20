import importlib.util
from pathlib import Path

import pytest

from docsage import __version__

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_release.py"


@pytest.fixture(scope="module")
def release():
    spec = importlib.util.spec_from_file_location("check_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_version_reads_the_source_file(release):
    assert release.package_version() == __version__


def test_package_version_rejects_a_file_without_a_version(release, tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text('"""No version here."""\n', encoding="utf-8")

    with pytest.raises(ValueError, match="no __version__"):
        release.package_version(init)


def test_release_problem_accepts_a_matching_tag(release):
    assert release.release_problem("v1.2.3", "1.2.3") is None


@pytest.mark.parametrize(
    ("tag", "version", "reason"),
    [
        ("v1.2.4", "1.2.3", "does not match"),
        ("1.2.3", "1.2.3", "does not match"),
        ("v1.2.3rc1", "1.2.3rc1", "MAJOR.MINOR.PATCH"),
        ("v1.2", "1.2", "MAJOR.MINOR.PATCH"),
    ],
)
def test_release_problem_explains_a_bad_tag(release, tag, version, reason):
    assert reason in release.release_problem(tag, version)


def test_main_checks_the_tag_against_the_package(release, capsys):
    assert release.main([f"v{__version__}"]) == 0
    assert f"Releasing docsage {__version__}" in capsys.readouterr().out

    assert release.main(["v999.0.0"]) == 1
    assert "Refusing to release" in capsys.readouterr().err


def test_main_falls_back_to_the_github_ref(release, monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", f"v{__version__}")
    assert release.main([]) == 0

    monkeypatch.delenv("GITHUB_REF_NAME")
    assert release.main([]) == 2


def test_release_workflow_runs_the_check_before_publishing():
    workflow = (SCRIPT.parents[1] / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert 'tags: ["v*.*.*"]' in workflow
    assert workflow.index("scripts/check_release.py") < workflow.index("python -m build")
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish" in workflow
