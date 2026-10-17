import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from docsage.domain.models import is_url
from docsage.infrastructure.web_loader import FetchedPage, HttpFetcher, WebPageLoader

PAGE = (
    "<html><head><title>Notes</title></head><body><nav>Menu</nav>"
    "<main><h1>Setup</h1><p>Install it.</p></main><footer>Bye</footer></body></html>"
)


def fetcher(content_type="text/html", body=PAGE, charset="utf-8", final_url=None):
    requested = []

    def fetch(url):
        requested.append(url)
        data = body.encode(charset or "utf-8") if isinstance(body, str) else body
        return FetchedPage(final_url or url, content_type, charset, data)

    fetch.requested = requested
    return fetch


def test_is_url_accepts_only_http_and_https():
    assert is_url("https://example.com/a")
    assert is_url("HTTP://example.com")
    assert not is_url("ftp://example.com")
    assert not is_url("docs/guide.md")


def test_html_pages_keep_their_main_content_title_and_final_url():
    fetch = fetcher(final_url="https://example.com/notes/")
    document = WebPageLoader(fetch).load("https://example.com/notes")

    assert fetch.requested == ["https://example.com/notes"]
    assert document.source == "https://example.com/notes"
    assert document.text == "# Setup\n\nInstall it."
    assert document.metadata == {
        "url": "https://example.com/notes/",
        "type": "html",
        "title": "Notes",
    }


def test_markdown_and_plain_text_are_kept_as_they_are():
    markdown = WebPageLoader(fetcher("text/markdown", "# A\n\nB")).load("https://x.io/a.md")
    text = WebPageLoader(fetcher("text/plain", "hello")).load("https://x.io/a.txt")

    assert (markdown.text, markdown.metadata["type"]) == ("# A\n\nB", "markdown")
    assert (text.text, text.metadata["type"]) == ("hello", "text")


def test_body_is_decoded_with_the_declared_charset_or_utf8():
    latin = WebPageLoader(fetcher("text/plain", "café", "latin-1")).load("https://x.io")
    unknown = WebPageLoader(fetcher("text/plain", "café".encode(), "no-such")).load("https://x.io")

    assert latin.text == "café"
    assert unknown.text == "café"


def test_binary_content_and_non_web_addresses_are_refused():
    with pytest.raises(ValueError, match="image/png"):
        WebPageLoader(fetcher("image/png", b"\x89PNG")).load("https://x.io/a.png")
    with pytest.raises(ValueError, match="http"):
        WebPageLoader(fetcher()).load("file:///etc/passwd")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode() if self.path == "/page" else b"x" * 100
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_http_fetcher_reads_the_page_and_its_content_type(server):
    page = HttpFetcher(timeout=5)(f"{server}/page")

    assert page.content_type == "text/html"
    assert page.charset == "utf-8"
    assert page.body == PAGE.encode()


def test_http_fetcher_refuses_pages_over_the_size_limit(server):
    with pytest.raises(OSError, match="larger than 10 bytes"):
        HttpFetcher(timeout=5, max_bytes=10)(f"{server}/big")


def test_http_fetcher_refuses_other_schemes():
    with pytest.raises(ValueError, match="http"):
        HttpFetcher()("file:///etc/passwd")
