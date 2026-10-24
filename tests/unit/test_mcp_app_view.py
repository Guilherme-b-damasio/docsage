import json
import re
import shutil
import subprocess

import pytest

from docsage.infrastructure.mcp_app_view import (
    HTML_META_KEY,
    PROTOCOL_VERSION,
    FollowUp,
    SliderControl,
    app_view,
)


def _script(html):
    return re.search(r"<script>(.*)</script>", html, re.S).group(1)


def test_view_is_a_self_contained_page_with_a_text_fallback():
    html = app_view("Index <dashboard>", "1.2.3")

    assert html.startswith("<!doctype html>")
    assert "<h1>Index &lt;dashboard&gt;</h1>" in html
    assert 'id="fallback"' in html
    assert "http://" not in html and "https://" not in html


def test_view_runs_the_mcp_apps_handshake():
    script = _script(app_view("Dashboard", "1.2.3"))

    assert script.index('"ui/initialize"') < script.index('"ui/notifications/initialized"')
    assert f'protocolVersion: "{PROTOCOL_VERSION}"' in script
    assert 'version: "1.2.3"' in script
    assert "window.parent.postMessage" in script


def test_view_reads_the_page_from_the_result_meta_and_follows_the_host_theme():
    script = _script(app_view("Dashboard", "1.2.3"))

    assert f'const META_KEY = "{HTML_META_KEY}";' in script
    assert '"ui/notifications/tool-result"' in script
    assert '"ui/notifications/host-context-changed"' in script
    assert "dataset.theme" in script
    assert '"ui/notifications/size-changed"' in script


def test_view_placeholders_are_all_filled():
    assert "__" not in _script(app_view("Dashboard", "1.2.3"))


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to parse the script")
def test_view_script_is_valid_javascript(tmp_path):
    source = tmp_path / "view.js"
    source.write_text(_script(app_view("Dashboard", "1.2.3")), encoding="utf-8")

    subprocess.run(["node", "--check", str(source)], check=True)


def test_view_asks_the_host_to_open_links_to_sources():
    script = _script(app_view("Answer", "1.2.3"))

    assert '"ui/open-link"' in script
    assert "event.preventDefault()" in script
    assert 'startsWith("#")' in script


FOLLOW_UP = FollowUp("ask_documents", "question", "Ask a follow-up question", "Ask")


def test_view_without_a_follow_up_has_no_form():
    script = _script(app_view("Dashboard", "1.2.3"))

    assert "const FOLLOW_UP = null;" in script


def test_follow_up_view_calls_the_tool_through_the_host():
    script = _script(app_view("Answer", "1.2.3", FOLLOW_UP))
    config = json.loads(re.search(r"const FOLLOW_UP = (\{.*?\});", script).group(1))

    assert config == {
        "tool": "ask_documents",
        "argument": "question",
        "label": "Ask a follow-up question",
        "action": "Ask",
    }
    assert '"tools/call"' in script
    assert "[FOLLOW_UP.argument]: text" in script


def test_follow_up_form_needs_a_host_that_proxies_tool_calls():
    script = _script(app_view("Answer", "1.2.3", FOLLOW_UP))

    assert "hostCapabilities.serverTools" in script
    assert "FOLLOW_UP && canCallTools" in script


def test_follow_up_shows_errors_instead_of_the_result():
    script = _script(app_view("Answer", "1.2.3", FOLLOW_UP))

    assert "result.isError" in script
    assert "call.reject" in script and "message.error" in script


def test_follow_up_form_keeps_its_styles_when_the_page_is_swapped_in():
    script = _script(app_view("Answer", "1.2.3", FOLLOW_UP))

    assert "form.follow-up" in script
    assert "style.textContent = VIEW_CSS" in script


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to parse the script")
def test_follow_up_view_script_is_valid_javascript(tmp_path):
    source = tmp_path / "view.js"
    source.write_text(_script(app_view("Answer", "1.2.3", FOLLOW_UP)), encoding="utf-8")

    subprocess.run(["node", "--check", str(source)], check=True)


SLIDER = SliderControl("index_dashboard", "top", "Top terms", 5, 50, 15, step=5)


def test_view_without_a_slider_has_no_slider_form():
    script = _script(app_view("Dashboard", "1.2.3"))

    assert "const SLIDER = null;" in script


def test_slider_view_calls_the_tool_with_the_chosen_number():
    script = _script(app_view("Dashboard", "1.2.3", slider=SLIDER))
    config = json.loads(re.search(r"const SLIDER = (\{.*?\});", script).group(1))

    assert config == {
        "tool": "index_dashboard",
        "argument": "top",
        "label": "Top terms",
        "minimum": 5,
        "maximum": 50,
        "value": 15,
        "step": 5,
    }
    assert "[SLIDER.argument]: chosen" in script
    assert "Number(input.value)" in script


def test_slider_form_needs_a_host_that_proxies_tool_calls():
    script = _script(app_view("Dashboard", "1.2.3", slider=SLIDER))

    assert "SLIDER && canCallTools" in script
    assert 'input.type = "range"' in script


def test_slider_keeps_the_number_it_was_left_on_across_results():
    script = _script(app_view("Dashboard", "1.2.3", slider=SLIDER))

    assert "let sliderValue = SLIDER ? SLIDER.value : 0;" in script
    assert "sliderValue = chosen;" in script
    assert "input.value = sliderValue;" in script


def test_slider_shows_errors_and_re_enables_itself():
    script = _script(app_view("Dashboard", "1.2.3", slider=SLIDER))

    assert "input.disabled = false;" in script
    assert "The tool call failed." in script


def test_slider_form_keeps_its_styles_when_the_page_is_swapped_in():
    script = _script(app_view("Dashboard", "1.2.3", slider=SLIDER))

    assert "form.refine" in script


def test_a_view_can_carry_both_a_follow_up_and_a_slider():
    script = _script(app_view("Dashboard", "1.2.3", FOLLOW_UP, SLIDER))

    assert "const FOLLOW_UP = {" in script
    assert "const SLIDER = {" in script
    assert "__" not in script


@pytest.mark.parametrize(
    "minimum, maximum, value, step",
    [(10, 10, 10, 1), (5, 50, 4, 1), (5, 50, 51, 1), (5, 50, 15, 0)],
)
def test_slider_rejects_a_range_it_cannot_offer(minimum, maximum, value, step):
    with pytest.raises(ValueError):
        SliderControl("index_dashboard", "top", "Top terms", minimum, maximum, value, step)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to parse the script")
def test_slider_view_script_is_valid_javascript(tmp_path):
    source = tmp_path / "view.js"
    source.write_text(_script(app_view("Dashboard", "1.2.3", FOLLOW_UP, SLIDER)), encoding="utf-8")

    subprocess.run(["node", "--check", str(source)], check=True)
