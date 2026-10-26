from docsage.infrastructure.headless_browser import find_browser, themed


def test_themed_pins_the_page_theme():
    html = '<!doctype html>\n<html lang="en">\n<body></body></html>'

    assert '<html data-theme="dark" lang="en">' in themed(html, "dark")


def test_find_browser_returns_the_first_existing_candidate(tmp_path):
    browser = tmp_path / "chrome.exe"
    browser.write_text("", encoding="utf-8")

    assert find_browser(["no-such-browser-xyz", str(browser)]) == str(browser)
    assert find_browser(["no-such-browser-xyz"]) is None
