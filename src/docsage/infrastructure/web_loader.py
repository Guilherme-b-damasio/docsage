"""Fetches web pages over HTTP(S) and keeps their main content as Markdown-like text.

Only the standard library is used: ``urllib`` fetches the page and the HTML loader's
main-content extraction drops navigation, headers and footers, so a page splits on its
headings like a local ``.html`` file and is cited as ``https://example.com/a, Setup``.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from docsage.domain.models import Document, is_url
from docsage.infrastructure.html_loader import main_content_to_text

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
MARKDOWN_TYPES = frozenset({"text/markdown", "text/x-markdown"})

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_BYTES = 5_000_000
USER_AGENT = "docsage (+https://github.com/Guilherme-b-damasio/docsage)"


@dataclass(frozen=True)
class FetchedPage:
    url: str
    """Where the page was finally read from, after redirects."""
    content_type: str
    """The media type without parameters, e.g. ``text/html``."""
    charset: str | None
    body: bytes


PageFetcher = Callable[[str], FetchedPage]


class HttpFetcher:
    """Reads a page with ``urllib``; pages larger than ``max_bytes`` are refused."""

    def __init__(
        self, timeout: float = DEFAULT_TIMEOUT_SECONDS, max_bytes: int = DEFAULT_MAX_BYTES
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes

    def __call__(self, url: str) -> FetchedPage:
        if not is_url(url):
            raise ValueError(f"Not an http(s) URL: {url}")
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            body = response.read(self._max_bytes + 1)
            if len(body) > self._max_bytes:
                raise OSError(f"{url} is larger than {self._max_bytes} bytes")
            return FetchedPage(
                url=response.geturl(),
                content_type=response.headers.get_content_type(),
                charset=response.headers.get_content_charset(),
                body=body,
            )


class WebPageLoader:
    """Loads HTML pages (main content only), Markdown and plain-text files from the web."""

    def __init__(self, fetch: PageFetcher | None = None) -> None:
        self._fetch = fetch or HttpFetcher()

    def load(self, url: str) -> Document:
        if not is_url(url):
            raise ValueError(f"Not an http(s) URL: {url}")
        page = self._fetch(url)
        text = _decode(page.body, page.charset)
        metadata = {"url": page.url}
        if page.content_type in HTML_TYPES:
            text, title = main_content_to_text(text)
            metadata["type"] = "html"
            if title:
                metadata["title"] = title
        elif page.content_type in MARKDOWN_TYPES:
            metadata["type"] = "markdown"
        elif page.content_type.startswith("text/"):
            metadata["type"] = "text"
        else:
            raise ValueError(f"Cannot index {page.content_type} content from {url}")
        # The requested URL stays the source, so re-indexing and removal find it again.
        return Document(source=url, text=text, metadata=metadata)


def _decode(body: bytes, charset: str | None) -> str:
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:  # an unknown charset name
        return body.decode("utf-8", errors="replace")
