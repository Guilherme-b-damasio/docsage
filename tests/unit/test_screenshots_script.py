import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "screenshots.py"


@pytest.fixture(scope="module")
def shots():
    spec = importlib.util.spec_from_file_location("screenshots", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_screenshot_command_runs_headless_at_the_given_size(shots, tmp_path):
    page = tmp_path / "page.html"

    command = shots.screenshot_command("chrome", page, tmp_path / "out.png", 1000, 800)

    assert command[0] == "chrome" and "--headless=new" in command
    assert "--window-size=1000,800" in command
    assert command[-1] == page.resolve().as_uri()


def test_demo_generator_cites_passages_without_calling_the_api(shots):
    answer = shots.DemoGenerator().generate("q", [])

    assert "[1]" in answer and "[2]" in answer


def test_main_without_a_browser_fails_with_a_hint(shots, monkeypatch, capsys):
    monkeypatch.setattr(shots, "find_browser", lambda: None)

    assert shots.main(["--out", "unused"]) == 1
    assert "pass --browser" in capsys.readouterr().err
