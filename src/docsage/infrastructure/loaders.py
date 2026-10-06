"""File loaders. Add a new format by adding a class, not by editing existing ones."""

from __future__ import annotations

from pathlib import Path

from docsage.domain.models import Document


class PlainTextLoader:
    """Loads UTF-8 text-like files (.txt, .md, .rst)."""

    EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".rst"})

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.EXTENSIONS

    def load(self, path: Path) -> Document:
        text = path.read_text(encoding="utf-8", errors="replace")
        return Document(source=str(path), text=text, metadata={"type": "text"})


class PdfLoader:
    """Loads PDFs page by page using pypdf (optional dependency)."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def load(self, path: Path) -> Document:
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = [page.extract_text() or "" for page in reader.pages]
        return Document(
            source=str(path),
            text="\n\n".join(pages),
            metadata={"type": "pdf", "pages": str(len(pages))},
        )


def default_loaders() -> list[PlainTextLoader | PdfLoader]:
    return [PlainTextLoader(), PdfLoader()]
