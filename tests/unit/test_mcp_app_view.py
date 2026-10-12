import re
import shutil
import subprocess

import pytest

from docsage.infrastructure.mcp_app_view import (
    HTML_META_KEY,
    PROTOCOL_VERSION,
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
