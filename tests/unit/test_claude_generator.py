from docsage.domain.models import Chunk, SearchResult
from docsage.infrastructure.claude_generator import build_prompt


def test_prompt_cites_the_pages_of_each_passage():
    chunk = Chunk(id="p", source="guide.pdf", text="BM25 ranks", position=0, first_page=4)

    prompt = build_prompt("how?", [SearchResult(chunk, 1.0)])

    assert "[1] (source: guide.pdf, p. 4)\nBM25 ranks" in prompt
    assert prompt.endswith("Question: how?")
