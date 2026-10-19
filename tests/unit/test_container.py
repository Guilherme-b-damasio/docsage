import zipfile
from pathlib import Path

import pytest

from docsage.container import DEFAULT_INDEX_PATH, Container, Settings, load_settings
from docsage.domain.models import TokenUsage
from docsage.infrastructure.web_loader import FetchedPage, WebPageLoader


def test_defaults_without_config():
    assert load_settings() == Settings()


def test_config_values_then_overrides(tmp_path):
    config = tmp_path / "docsage.toml"
    config.write_text("chunk_size = 80\nmodel = 'from-config'\n", encoding="utf-8")

    settings = load_settings(config, model="from-flag", index_path=None)

    assert settings.chunk_size == 80
    assert settings.model == "from-flag"
    assert settings.index_path == DEFAULT_INDEX_PATH
    assert isinstance(settings.index_path, Path)


def test_catalog_service_reads_the_configured_index(tmp_path):
    from docsage.container import Container

    service = Container(Settings(index_path=tmp_path / "index.json")).catalog_service()

    assert service.documents() == []


def test_question_answering_uses_an_injected_generator(tmp_path):
    from docsage.container import Container
    from docsage.domain.models import Chunk

    class FakeGenerator:
        def generate(self, question, context):
            return f"{question} -> {len(context)} passages"

    container = Container(Settings(index_path=tmp_path / "index.json"), FakeGenerator())
    notes = tmp_path / "notes.md"
    notes.write_text("Lisbon is the capital of Portugal.", encoding="utf-8")
    container.indexing_service().index([notes])

    answer = container.question_answering_service().ask("Where is Lisbon?")

    assert answer.text == "Where is Lisbon? -> 1 passages"
    assert isinstance(answer.sources[0].chunk, Chunk)


def test_search_results_carry_highlights_from_the_shared_tokenizer(tmp_path):
    from docsage.container import Container

    container = Container(Settings(index_path=tmp_path / "index.json"))
    notes = tmp_path / "notes.md"
    notes.write_text("The Index lives on disk.", encoding="utf-8")
    container.indexing_service().index([notes])

    (result,) = container.search_service().search("where is the index?")

    assert result.matched_terms == ("index",)
    (highlight,) = result.highlights
    assert result.chunk.text[highlight.start : highlight.end] == "Index"


def test_answer_report_service_renders_html_or_text(tmp_path):
    import pytest

    from docsage.container import Container

    class FakeGenerator:
        def generate(self, question, context):
            return "Lisbon [1]."

    container = Container(Settings(index_path=tmp_path / "index.json"), FakeGenerator())
    notes = tmp_path / "notes.md"
    notes.write_text("Lisbon is the capital of Portugal.", encoding="utf-8")
    container.indexing_service().index([notes])

    html = container.answer_report_service().report("Where is Lisbon?")
    text = container.answer_report_service("text").report("Where is Lisbon?")

    assert html.answer.text == "Lisbon [1]."
    assert '<mark title="lisbon">Lisbon</mark>' in html.content
    assert "**Lisbon**" in text.content
    with pytest.raises(ValueError, match="Unknown report format"):
        container.answer_report_service("pdf")


def test_dashboard_service_rejects_unknown_formats(tmp_path):
    import pytest

    from docsage.container import Container

    container = Container(Settings(index_path=tmp_path / "index.json"))

    assert "The index is empty" in container.dashboard_service().render()
    with pytest.raises(ValueError, match="Unknown dashboard format"):
        container.dashboard_service("svg")


class _KeywordEmbedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[float("lisbon" in text.lower()), float("tokyo" in text.lower())] for text in texts]


def test_embedding_retriever_ranks_with_the_injected_embedder_and_caches_vectors(tmp_path):
    from docsage.container import Container

    settings = Settings(index_path=tmp_path / "index.json", retriever="embedding")
    embedder = _KeywordEmbedder()
    container = Container(settings, embedder=embedder)
    for name, text in [("pt.md", "Lisbon is in Portugal."), ("jp.md", "Tokyo is in Japan.")]:
        (tmp_path / name).write_text(text, encoding="utf-8")
        container.indexing_service().index([tmp_path / name])

    (result,) = container.search_service().search("lisbon", top_k=1)

    assert result.chunk.source.endswith("pt.md")
    assert (tmp_path / "index.embeddings.json").is_file()
    embedder.texts.clear()
    Container(settings, embedder=embedder).search_service().search("tokyo", top_k=1)
    assert embedder.texts == ["tokyo"]


def test_unknown_retriever_is_rejected():
    import pytest

    from docsage.infrastructure.config import ConfigError

    with pytest.raises(ConfigError, match="Unknown retriever"):
        load_settings(retriever="magic")


def test_hybrid_retriever_finds_chunks_either_ranking_misses(tmp_path):
    from docsage.container import Container

    settings = Settings(index_path=tmp_path / "index.json", retriever="hybrid")
    container = Container(settings, embedder=_KeywordEmbedder())
    notes = tmp_path / "notes.md"
    notes.write_text("# Lisbon\n\nCapital of Portugal.\n\n# Japan\n\nIts capital.\n", "utf-8")
    container.indexing_service().index([notes])

    results = container.search_service().search("lisbon capital", top_k=2)

    assert len(results) == 2
    assert results[0].chunk.section == "Lisbon"
    assert results[0].contributions == ()


class _ReversingReranker:
    def __init__(self) -> None:
        self.calls = 0

    def rerank(self, query, candidates):
        from docsage.domain.models import SearchResult

        self.calls += 1
        return [SearchResult(result.chunk, 1.0) for result in reversed(candidates)]


def _two_notes(container, tmp_path):
    first = tmp_path / "a.md"
    first.write_text("lisbon lisbon lisbon", encoding="utf-8")
    second = tmp_path / "b.md"
    second.write_text("lisbon and porto", encoding="utf-8")
    container.indexing_service().index([first, second])


def test_rerank_setting_puts_the_reranker_in_front_of_search(tmp_path):
    from docsage.container import Container

    reranker = _ReversingReranker()
    settings = Settings(index_path=tmp_path / "index.json", rerank=True)
    container = Container(settings, reranker=reranker)
    _two_notes(container, tmp_path)

    results = container.search_service().search("lisbon", top_k=2)

    assert [Path(result.chunk.source).name for result in results] == ["b.md", "a.md"]
    assert results[0].highlights
    assert reranker.calls == 1


def test_search_skips_the_reranker_when_rerank_is_off(tmp_path):
    from docsage.container import Container

    reranker = _ReversingReranker()
    container = Container(Settings(index_path=tmp_path / "index.json"), reranker=reranker)
    _two_notes(container, tmp_path)

    (best, _) = container.search_service().search("lisbon", top_k=2)

    assert Path(best.chunk.source).name == "a.md"
    assert reranker.calls == 0


def test_rerank_candidates_must_be_positive():
    import pytest

    from docsage.infrastructure.config import ConfigError

    with pytest.raises(ConfigError, match="rerank_candidates"):
        load_settings(rerank_candidates=0)


def test_dashboard_maps_chunks_only_for_embedding_retrievers(tmp_path):
    from docsage.container import Container

    for name, text in [("pt.md", "Lisbon is in Portugal."), ("jp.md", "Tokyo is in Japan.")]:
        (tmp_path / name).write_text(text, encoding="utf-8")
    files = [tmp_path / "pt.md", tmp_path / "jp.md"]

    hybrid = Settings(index_path=tmp_path / "index.json", retriever="hybrid")
    container = Container(hybrid, embedder=_KeywordEmbedder())
    container.indexing_service().index(files)
    points = container.dashboard_service().overview().chunk_map

    assert sorted(Path(point.source).name for point in points) == ["jp.md", "pt.md"]
    bm25 = Settings(index_path=tmp_path / "index.json")
    embedder = _KeywordEmbedder()
    assert Container(bm25, embedder=embedder).dashboard_service().overview().chunk_map == ()
    assert embedder.texts == []


def test_evaluation_service_scores_the_configured_retriever(tmp_path):
    import pytest

    from docsage.container import Container
    from docsage.domain.models import EvaluationCase

    container = Container(Settings(index_path=tmp_path / "index.json"))
    for name, text in [("pt.md", "Lisbon is in Portugal."), ("jp.md", "Tokyo is in Japan.")]:
        (tmp_path / name).write_text(text, encoding="utf-8")
    container.indexing_service().index(sorted(tmp_path.glob("*.md")))
    cases = [EvaluationCase("Tokyo", ("jp.md",)), EvaluationCase("Lisbon", ("jp.md",))]

    service = container.evaluation_service("html")
    report = service.evaluate(cases, k=2)

    assert [outcome.first_hit for outcome in report.outcomes] == [1, None]
    assert report.mrr == 0.5
    assert "<svg" in service.render(report)
    with pytest.raises(ValueError, match="Unknown evaluation format"):
        container.evaluation_service("pdf")


def test_unknown_chunker_is_rejected():
    import pytest

    from docsage.infrastructure.config import ConfigError

    with pytest.raises(ConfigError, match="Unknown chunker: lines"):
        load_settings(chunker="lines")


def test_sentence_chunker_setting_keeps_sentences_whole(tmp_path):
    from docsage.container import Container

    notes = tmp_path / "notes.txt"
    notes.write_text("One two three. Four five six. Seven eight nine.", encoding="utf-8")
    guide = tmp_path / "guide.md"
    guide.write_text("# Setup\n\nAlpha beta gamma. Delta epsilon zeta.", encoding="utf-8")
    settings = Settings(
        index_path=tmp_path / "index.json", chunk_size=5, chunk_overlap=0, chunker="sentence"
    )
    container = Container(settings)

    container.indexing_service().index([notes, guide])

    texts = {chunk.text for chunk in container.catalog_service().document_chunks(str(notes))}
    assert texts == {"One two three.", "Four five six.", "Seven eight nine."}
    sections = container.catalog_service().document_chunks(str(guide))
    assert [chunk.text for chunk in sections] == [
        "# Setup Alpha beta gamma.",
        "Delta epsilon zeta.",
    ]
    assert {chunk.section for chunk in sections} == {"Setup"}


def test_prompt_cache_setting_reaches_the_claude_generator(tmp_path, monkeypatch):
    from docsage.container import Container
    from docsage.infrastructure import claude_generator

    built = []

    class FakeClaudeGenerator:
        def __init__(self, **kwargs):
            built.append(kwargs)

    monkeypatch.setattr(claude_generator, "ClaudeAnswerGenerator", FakeClaudeGenerator)
    settings = Settings(index_path=tmp_path / "index.json", model="m", prompt_cache=False)

    Container(settings).question_answering_service()
    Container(Settings(index_path=tmp_path / "index.json")).question_answering_service()

    assert [(kwargs.get("model"), kwargs["cache_context"]) for kwargs in built] == [
        ("m", False),
        (None, True),
    ]


def test_chat_service_uses_a_conversational_generator(tmp_path):
    from docsage.container import Container

    class FakeConversationalGenerator:
        def generate(self, question, context):
            return "single"

        def converse(self, question, context, history):
            yield "chat"

    settings = Settings(index_path=tmp_path / "index.json", chat_history_turns=3)
    container = Container(settings, FakeConversationalGenerator())
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    container.indexing_service().index([tmp_path / "a.md"])

    assert container.chat_service().ask("alpha").text == "chat"


def test_chat_service_rejects_a_generator_that_cannot_converse(tmp_path):
    import pytest

    from docsage.container import Container

    class SingleShotGenerator:
        def generate(self, question, context):
            return "single"

    container = Container(Settings(index_path=tmp_path / "index.json"), SingleShotGenerator())

    with pytest.raises(TypeError, match="cannot hold a conversation"):
        container.chat_service()


def test_chat_history_turns_comes_from_the_config_file(tmp_path):
    import pytest

    from docsage.infrastructure.config import ConfigError

    config = tmp_path / "docsage.toml"
    config.write_text("chat_history_turns = 4\n", encoding="utf-8")
    assert load_settings(config).chat_history_turns == 4

    config.write_text("chat_history_turns = -1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(config)


def test_answer_style_settings_reach_the_claude_generator(tmp_path, monkeypatch):
    from docsage.container import Container
    from docsage.domain.models import AnswerStyle
    from docsage.infrastructure import claude_generator

    built = []

    class FakeClaudeGenerator:
        def __init__(self, **kwargs):
            built.append(kwargs)

    monkeypatch.setattr(claude_generator, "ClaudeAnswerGenerator", FakeClaudeGenerator)
    settings = Settings(
        index_path=tmp_path / "index.json", answer_language="Portuguese", answer_length="long"
    )

    Container(settings).question_answering_service()

    assert built[0]["style"] == AnswerStyle("Portuguese", "long")


def test_answer_style_comes_from_the_config_file(tmp_path):
    import pytest

    from docsage.infrastructure.config import ConfigError

    config = tmp_path / "docsage.toml"
    config.write_text('answer_language = "Spanish"\nanswer_length = "short"\n', encoding="utf-8")
    settings = load_settings(config)
    assert (settings.answer_language, settings.answer_length) == ("Spanish", "short")

    assert load_settings(config, answer_length="long").answer_length == "long"

    config.write_text('answer_length = "huge"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="Unknown answer length"):
        load_settings(config)


def test_answers_from_the_container_are_priced(tmp_path):
    class Generator:
        last_usage = None

        def generate(self, question, context):
            self.last_usage = TokenUsage(
                model="claude-opus-5-5", input_tokens=1000, output_tokens=500
            )
            return "an answer"

    container = Container(Settings(index_path=tmp_path / "index.json"), generator=Generator())
    (tmp_path / "doc.md").write_text("Paris is the capital of France.", encoding="utf-8")
    container.indexing_service().index([tmp_path / "doc.md"])

    answer = container.question_answering_service().ask("capital of France?")

    assert answer.cost_usd == pytest.approx(0.014)


def test_html_pages_are_indexed_by_section(tmp_path):
    page = tmp_path / "guide.html"
    page.write_text(
        "<html><body><h1>Setup</h1><p>Install the package.</p>"
        "<h2>Upgrade</h2><p>Run the upgrade command.</p></body></html>",
        encoding="utf-8",
    )
    container = Container(Settings(index_path=tmp_path / "index.json"))

    report = container.indexing_service().index([page])
    results = container.search_service().search("upgrade command", top_k=1)

    assert (report.documents, report.skipped) == (1, ())
    assert results[0].chunk.citation == f"{page}, Setup > Upgrade"


def test_word_documents_are_indexed_by_section(tmp_path):
    def heading(text, level):
        style = f'<w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>'
        return f"<w:p>{style}<w:r><w:t>{text}</w:t></w:r></w:p>"

    def body(text):
        return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"

    document = tmp_path / "guide.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{heading('Setup', 1)}{body('Install the package.')}"
            f"{heading('Upgrade', 2)}{body('Run the upgrade command.')}</w:body></w:document>",
        )
    container = Container(Settings(index_path=tmp_path / "index.json"))

    report = container.indexing_service().index([document])
    results = container.search_service().search("upgrade command", top_k=1)

    assert (report.documents, report.skipped) == (1, ())
    assert results[0].chunk.citation == f"{document}, Setup > Upgrade"


def test_web_pages_are_indexed_by_section_under_their_url(tmp_path):
    page = (
        "<html><body><nav>Home Pricing</nav><main><h1>Setup</h1><p>Install it.</p>"
        "<h2>Upgrade</h2><p>Run the upgrade command.</p></main></body></html>"
    )
    loader = WebPageLoader(lambda url: FetchedPage(url, "text/html", "utf-8", page.encode()))
    container = Container(Settings(index_path=tmp_path / "index.json"), url_loader=loader)

    report = container.indexing_service().index_urls(["https://x.io/guide"])
    results = container.search_service().search("upgrade command", top_k=1)

    assert (report.documents, report.failed) == (1, ())
    assert results[0].chunk.citation == "https://x.io/guide, Setup > Upgrade"
    assert container.search_service().search("pricing", top_k=1) == []


def test_watch_service_shares_one_index_between_indexing_and_removal(tmp_path):
    from docsage.domain.models import FileChanges

    docs = tmp_path / "docs"
    docs.mkdir()
    a, b = docs / "a.md", docs / "b.md"
    a.write_text("alpha notes", encoding="utf-8")
    b.write_text("beta notes", encoding="utf-8")

    class ScriptedWatcher:
        def watch(self, roots):
            yield FileChanges(changed=(a, b))
            a.unlink()
            yield FileChanges(removed=(a,))

    settings = Settings(index_path=tmp_path / "index.json")
    updates = list(Container(settings, watcher=ScriptedWatcher()).watch_service().watch([docs]))

    assert [update.indexing.documents for update in updates] == [2, 0]
    assert updates[1].removed == (str(a),)
    sources = [document.source for document in Container(settings).catalog_service().documents()]
    assert sources == [str(b)]


def test_watch_service_polls_without_looking_inside_the_index_folder(tmp_path):
    index_path = tmp_path / ".docsage" / "index.json"
    index_path.parent.mkdir()
    index_path.write_text('{"chunks": []}', encoding="utf-8")
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")

    service = Container(Settings(index_path=index_path)).watch_service(interval=0.1)
    first = next(service.watch([tmp_path]))

    assert first.changes.changed == (tmp_path / "a.md",)
