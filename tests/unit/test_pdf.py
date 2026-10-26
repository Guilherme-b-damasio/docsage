import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from docsage.infrastructure.pdf import HeadlessChromePdfPrinter, PdfExportError, print_command

PAGE = '<!doctype html>\n<html lang="en">\n<body>hi</body></html>'


class FakeBrowser:
    """Records each command and "prints" by writing a stub PDF where it was asked to."""

    def __init__(self, returncode=0, write=True, stderr=""):
        self.commands = []
        self.pages = []
        self._returncode = returncode
        self._write = write
        self._stderr = stderr

    def __call__(self, command, **options):
        self.commands.append(command)
        target = next(arg for arg in command if arg.startswith("--print-to-pdf="))
        pdf = Path(target.split("=", 1)[1])
        self.pages.append((pdf.parent / "page.html").read_text(encoding="utf-8"))
        if self._write:
            pdf.write_bytes(b"%PDF-1.7 fake")
        return SimpleNamespace(returncode=self._returncode, stderr=self._stderr)


def test_print_command_prints_headless_without_header_and_footer(tmp_path):
    page = tmp_path / "page.html"

    command = print_command("chrome", page, tmp_path / "out.pdf", tmp_path / "profile")

    assert command[0] == "chrome" and "--headless=new" in command
    assert "--no-pdf-header-footer" in command
    assert f"--print-to-pdf={tmp_path / 'out.pdf'}" in command
    assert f"--user-data-dir={tmp_path / 'profile'}" in command
    assert command[-1] == page.resolve().as_uri()


def test_printer_returns_the_pdf_of_a_light_page():
    browser = FakeBrowser()

    pdf = HeadlessChromePdfPrinter("chrome", run=browser).print_pdf(PAGE)

    assert pdf == b"%PDF-1.7 fake"
    assert browser.commands[0][0] == "chrome"
    assert '<html data-theme="light" lang="en">' in browser.pages[0]


def test_printer_searches_for_a_browser_when_none_is_given(tmp_path):
    executable = tmp_path / "chrome.exe"
    executable.write_text("", encoding="utf-8")
    browser = FakeBrowser()

    HeadlessChromePdfPrinter(run=browser, candidates=[str(executable)]).print_pdf(PAGE)

    assert browser.commands[0][0] == str(executable)


def test_printer_without_a_browser_says_how_to_pass_one():
    printer = HeadlessChromePdfPrinter(run=FakeBrowser(), candidates=["no-such-browser-xyz"])

    with pytest.raises(PdfExportError, match="pass --browser"):
        printer.print_pdf(PAGE)


def test_printer_reports_a_browser_that_fails():
    browser = FakeBrowser(returncode=1, write=False, stderr="warning\nbad flag")

    with pytest.raises(PdfExportError, match="could not print the page: bad flag"):
        HeadlessChromePdfPrinter("chrome", run=browser).print_pdf(PAGE)


def test_printer_reports_a_browser_that_cannot_start():
    def missing(command, **options):
        raise FileNotFoundError(command[0])

    with pytest.raises(PdfExportError, match="Could not run chrome"):
        HeadlessChromePdfPrinter("chrome", run=missing).print_pdf(PAGE)


def test_printer_reports_a_browser_that_hangs():
    def hang(command, **options):
        raise subprocess.TimeoutExpired(command, options["timeout"])

    with pytest.raises(PdfExportError, match="Could not run chrome"):
        HeadlessChromePdfPrinter("chrome", run=hang).print_pdf(PAGE)


def test_pages_keep_cards_whole_when_printed():
    from docsage.infrastructure.html_page import page

    html = page("t", "<p>x</p>")

    assert "@media print" in html
    assert ".card, figure, table { break-inside: avoid; }" in html
