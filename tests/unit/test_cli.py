import json
from pathlib import Path

from docsage.interfaces.cli import main


def test_remove_command_drops_indexed_file(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    (tmp_path / "b.md").write_text("beta notes", encoding="utf-8")
    assert main(["--index", str(index), "index", str(tmp_path)]) == 0

    assert main(["--index", str(index), "remove", str(tmp_path / "a.md")]) == 0
    assert "Removed 1 documents (1 chunks)." in capsys.readouterr().out

    assert main(["--index", str(index), "search", "alpha"]) == 1
    assert main(["--index", str(index), "search", "beta"]) == 0


def test_remove_command_reports_missing_path(tmp_path, capsys):
    index = tmp_path / "index.json"
    assert main(["--index", str(index), "remove", str(tmp_path / "nope.md")]) == 1
    assert "Nothing indexed under" in capsys.readouterr().err


def test_index_command_skips_unchanged_files_unless_forced(tmp_path, capsys):
    index = tmp_path / ".docsage" / "index.json"
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(docs)])
    capsys.readouterr()

    main(["--index", str(index), "index", str(docs)])
    out = capsys.readouterr().out
    assert "Indexed 0 documents" in out
    assert "Skipped 1 unchanged documents" in out

    main(["--index", str(index), "index", "--force", str(docs)])
    assert "Indexed 1 documents" in capsys.readouterr().out


def test_search_ignores_stopwords(tmp_path):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("The capital of France is Paris.", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path / "a.md")])

    assert main(["--index", str(index), "search", "what is the"]) == 1
    assert main(["--index", str(index), "search", "qual é a capital"]) == 0


def test_search_json_output(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "search", "alpha", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "alpha"
    assert payload["results"][0]["chunk"]["source"].endswith("a.md")

    assert main(["--index", str(index), "search", "missing", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["results"] == []


def test_ask_json_output(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    index = tmp_path / "index.json"
    # Empty index: the service answers without calling the generator.
    assert main(["--index", str(index), "ask", "anything?", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "question": "anything?",
        "answer": "No relevant context found in the index.",
        "sources": [],
    }


def test_config_file_sets_index_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docsage.toml").write_text('index_path = "store/idx.json"\n', encoding="utf-8")
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")

    assert main(["index", "a.md"]) == 0
    assert (tmp_path / "store" / "idx.json").is_file()
    assert main(["search", "alpha"]) == 0


def test_index_flag_overrides_config_file(tmp_path, capsys):
    config = tmp_path / "custom.toml"
    config.write_text('index_path = "from-config.json"\n', encoding="utf-8")
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    index = tmp_path / "from-flag.json"

    main(["--config", str(config), "--index", str(index), "index", str(tmp_path / "a.md")])

    assert index.is_file()
    assert not (tmp_path / "from-config.json").exists()


def test_invalid_config_file_is_reported(tmp_path, capsys):
    config = tmp_path / "bad.toml"
    config.write_text("chunk_size = 'big'\n", encoding="utf-8")

    assert main(["--config", str(config), "search", "x"]) == 2
    assert "chunk_size" in capsys.readouterr().err


def test_stats_command(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha alpha beta", encoding="utf-8")
    (tmp_path / "b.md").write_text("alpha gamma", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "stats", "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert "Documents:  2" in out
    assert "Terms:      5 (3 distinct)" in out
    assert "alpha  3" in out
    assert "beta" not in out

    assert main(["--index", str(index), "stats", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chunks"] == 2
    assert payload["top_terms"][0] == {"term": "alpha", "count": 3}
    assert payload["index_bytes"] == index.stat().st_size


def test_stats_on_empty_index(tmp_path, capsys):
    assert main(["--index", str(tmp_path / "none.json"), "stats"]) == 0
    out = capsys.readouterr().out
    assert "Documents:  0" in out
    assert "Index size: 0 B" in out


def test_search_cites_the_markdown_section(tmp_path, capsys):
    index = tmp_path / "index.json"
    guide = tmp_path / "guide.md"
    guide.write_text("# Guide\n\n## Install\n\nRun pip install docsage.\n", encoding="utf-8")
    main(["--index", str(index), "index", str(guide)])
    capsys.readouterr()

    assert main(["--index", str(index), "search", "pip"]) == 0
    assert f"{guide}, Guide > Install" in capsys.readouterr().out


def test_verbose_flag_logs_events_to_stderr(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")

    assert main(["--verbose", "--index", str(index), "index", str(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert "Indexed 1 documents" in captured.out
    assert "level=debug logger=docsage.application.services event=\"indexed document\"" in (
        captured.err
    )
    assert "event=\"indexing finished\" documents=1 chunks=1" in captured.err


def test_logs_are_quiet_without_verbose(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")

    main(["--index", str(index), "index", str(tmp_path)])

    assert "event=" not in capsys.readouterr().err


def test_search_lists_the_matched_terms(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("Paris is the capital of France.", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path / "a.md")])
    capsys.readouterr()

    assert main(["--index", str(index), "search", "capital of france"]) == 0
    assert "(matched: capital, france)" in capsys.readouterr().out


def test_dashboard_command_writes_an_html_file(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes about retrieval", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path / "a.md")])
    capsys.readouterr()
    output = tmp_path / "out" / "dashboard.html"

    assert main(["--index", str(index), "dashboard", "-o", str(output)]) == 0

    assert f"Wrote {output}" in capsys.readouterr().out
    html = output.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "<title>md: 1</title>" in html


def test_dashboard_command_prints_text(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha alpha beta", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path / "a.md")])
    capsys.readouterr()

    assert main(["--index", str(index), "dashboard", "--format", "text", "--top", "1"]) == 0

    out = capsys.readouterr().out
    assert "Documents:  1" in out
    assert "Top terms:\n  alpha" in out
    assert "beta" not in out


def test_dashboard_falls_back_to_utf8_bytes_on_a_narrow_stdout(tmp_path, monkeypatch):
    import io
    import sys

    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha beta", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path / "a.md")])
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))

    assert main(["--index", str(index), "dashboard", "--format", "text"]) == 0

    sys.stdout.flush()
    assert "█" in raw.getvalue().decode("utf-8")


def test_search_explain_prints_the_score_breakdown(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha beta notes", encoding="utf-8")
    (tmp_path / "b.md").write_text("gamma notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "search", "alpha beta", "--explain"]) == 0
    explained = capsys.readouterr().out.split("   score = ")[1]
    assert "alpha " in explained and "beta " in explained


def test_search_hides_the_breakdown_without_explain(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "search", "alpha"]) == 0
    assert "score = " not in capsys.readouterr().out


class _FakeGenerator:
    def generate(self, question, context):
        return f"Alpha is described in [1]. ({len(context)} passages)"


def _offline(monkeypatch):
    """Makes the CLI build containers whose generator never calls the Claude API."""
    import docsage.interfaces.cli as cli
    from docsage.container import Container

    monkeypatch.setattr(cli, "Container", lambda settings: Container(settings, _FakeGenerator()))


def test_report_writes_an_html_answer_report(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    output = tmp_path / "out" / "answer.html"

    assert main(["--index", str(index), "report", "what is alpha?", "-o", str(output)]) == 0

    html = output.read_text(encoding="utf-8")
    assert "<h1>what is alpha?</h1>" in html
    assert '<a class="cite" href="#source-1">[1]</a>' in html
    assert f"Wrote {output}" in capsys.readouterr().out


def test_report_prints_the_text_format_to_stdout(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "report", "alpha?", "--format", "text"]) == 0

    out = capsys.readouterr().out
    assert out.splitlines()[:2] == ["alpha?", "======"]
    assert "**alpha** notes" in out


def _indexed(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()
    return index


def test_report_open_writes_a_temporary_file_and_opens_it(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    index = _indexed(tmp_path, capsys)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)

    assert main(["--index", str(index), "report", "alpha?", "--open"]) == 0

    (url,) = opened
    assert url.startswith("file:") and url.endswith("/report.html")
    written = Path(capsys.readouterr().out.removeprefix("Wrote ").strip())
    assert written.as_uri() == url
    assert "<h1>alpha?</h1>" in written.read_text(encoding="utf-8")


def test_report_open_uses_the_output_path_when_given(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    index = _indexed(tmp_path, capsys)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    output = tmp_path / "answer.txt"

    args = ["--index", str(index), "report", "alpha?", "--format", "text", "-o", str(output)]
    assert main([*args, "--open"]) == 0

    assert opened == [output.resolve().as_uri()]


def test_report_open_says_where_the_file_is_without_a_browser(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    index = _indexed(tmp_path, capsys)
    monkeypatch.setattr("webbrowser.open", lambda url: False)

    assert main(["--index", str(index), "report", "alpha?", "--open"]) == 0

    assert "could not open a browser, the report is at" in capsys.readouterr().err


def test_dashboard_command_prints_a_mermaid_diagram_of_related_documents(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("retrieval ranking with bm25", encoding="utf-8")
    (tmp_path / "b.md").write_text("bm25 ranking explained", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "dashboard", "--format", "mermaid"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("graph LR\n")
    assert '["a.md"]' in out and '["b.md"]' in out
    assert "bm25" in out and "ranking" in out


def test_unknown_retriever_in_config_is_reported(tmp_path, capsys):
    config = tmp_path / "docsage.toml"
    config.write_text("retriever = 'magic'\n", encoding="utf-8")

    assert main(["--config", str(config), "search", "x"]) == 2
    assert "Unknown retriever: magic" in capsys.readouterr().err


def test_retriever_flag_accepts_only_known_strategies(tmp_path, capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["--retriever", "magic", "search", "x"])
    assert "invalid choice" in capsys.readouterr().err


def test_rerank_flag_lets_claude_reorder_the_results(tmp_path, capsys, monkeypatch):
    from docsage.domain.models import SearchResult
    from docsage.infrastructure import claude_reranker

    class FakeReranker:
        def __init__(self, **options):
            pass

        def rerank(self, query, candidates):
            return [SearchResult(result.chunk, 7.0) for result in reversed(candidates)]

    monkeypatch.setattr(claude_reranker, "ClaudeReranker", FakeReranker)
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("lisbon lisbon lisbon", encoding="utf-8")
    (tmp_path / "b.md").write_text("lisbon and porto", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "--rerank", "search", "lisbon", "--json"]) == 0

    hits = json.loads(capsys.readouterr().out)["results"]
    assert [Path(hit["chunk"]["source"]).name for hit in hits] == ["b.md", "a.md"]
    assert {hit["score"] for hit in hits} == {7.0}


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _indexed_corpus(tmp_path, capsys):
    index = tmp_path / "index.json"
    assert main(["--index", str(index), "index", str(FIXTURES / "corpus")]) == 0
    capsys.readouterr()
    return index


def test_evaluate_prints_recall_and_mrr(tmp_path, capsys):
    index = _indexed_corpus(tmp_path, capsys)

    labels = str(FIXTURES / "evaluation.json")
    assert main(["--index", str(index), "evaluate", labels, "-k", "3"]) == 0
    out = capsys.readouterr().out
    assert "Queries:              7" in out
    assert "Recall@3:" in out
    assert "Mean reciprocal rank:" in out


def test_evaluate_json_output(tmp_path, capsys):
    index = _indexed_corpus(tmp_path, capsys)
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps([{"query": "where is the index stored", "relevant": ["faq.txt"]}]), "utf-8"
    )

    assert main(["--index", str(index), "evaluate", str(labels), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["k"] == 5
    assert payload["queries"] == 1
    assert payload["cases"][0]["first_hit"] == 1
    assert payload["recall"] == payload["mrr"] == 1.0
    assert len(payload["recall_curve"]) == 5


def test_evaluate_writes_an_html_report(tmp_path, capsys):
    index = _indexed_corpus(tmp_path, capsys)
    output = tmp_path / "eval.html"

    labels = str(FIXTURES / "evaluation.json")
    args = ["--index", str(index), "evaluate", labels, "--format", "html", "-o", str(output)]
    assert main(args) == 0
    assert f"Wrote {output}" in capsys.readouterr().out
    assert "Recall by cut-off" in output.read_text("utf-8")


def test_evaluate_reports_a_bad_label_file(tmp_path, capsys):
    labels = tmp_path / "labels.json"
    labels.write_text("[]", "utf-8")

    assert main(["--index", str(tmp_path / "i.json"), "evaluate", str(labels)]) == 2
    assert "non-empty list" in capsys.readouterr().err


def test_evaluate_rejects_a_zero_cut_off(tmp_path, capsys):
    labels = str(FIXTURES / "evaluation.json")
    assert main(["--index", str(tmp_path / "i.json"), "evaluate", labels, "-k", "0"]) == 2
    assert "--top-k" in capsys.readouterr().err


def test_index_chunker_flag_selects_the_sentence_chunker(tmp_path, capsys):
    index = tmp_path / "index.json"
    words = " ".join(f"w{i}" for i in range(190))
    tail = "Zebra tail sentence " + " ".join(f"t{i}" for i in range(12)) + "."
    (tmp_path / "a.txt").write_text(f"{words}. {tail}", encoding="utf-8")

    assert main(["--index", str(index), "index", "--chunker", "sentence", str(tmp_path)]) == 0
    capsys.readouterr()

    # A 200-word window would cut the tail sentence; the sentence chunker keeps it whole.
    assert main(["--index", str(index), "search", "zebra", "--json"]) == 0
    texts = [item["chunk"]["text"] for item in json.loads(capsys.readouterr().out)["results"]]
    assert texts == [tail]


def test_unknown_chunker_flag_is_rejected(tmp_path, capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["--index", str(tmp_path / "i.json"), "index", "--chunker", "lines", str(tmp_path)])
    assert "invalid choice" in capsys.readouterr().err


class _FakeStreamingGenerator(_FakeGenerator):
    def stream(self, question, context):
        yield "Alpha is "
        yield "described in [1]."


def test_ask_streams_the_answer_then_lists_sources(tmp_path, capsys, monkeypatch):
    import docsage.interfaces.cli as cli
    from docsage.container import Container

    monkeypatch.setattr(
        cli, "Container", lambda settings: Container(settings, _FakeStreamingGenerator())
    )
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "ask", "alpha?"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("Alpha is described in [1].\n")
    assert "Sources:" in out


def test_ask_no_stream_prints_the_complete_answer(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "ask", "alpha?", "--no-stream"]) == 0

    assert capsys.readouterr().out.startswith("Alpha is described in [1]. (1 passages)\n")


class _FakeConversationalGenerator(_FakeGenerator):
    def __init__(self):
        self.histories = []

    def converse(self, question, context, history):
        self.histories.append([turn.question for turn in history])
        yield f"Turn {len(history) + 1}: "
        yield "see [1]."


def _chat(tmp_path, monkeypatch, lines):
    import io

    import docsage.interfaces.cli as cli
    from docsage.container import Container

    generator = _FakeConversationalGenerator()
    monkeypatch.setattr(cli, "Container", lambda settings: Container(settings, generator))
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(f"{line}\n" for line in lines)))
    return generator, main(["--index", str(index), "chat"])


def test_chat_answers_follow_ups_with_the_earlier_turns(tmp_path, capsys, monkeypatch):
    generator, code = _chat(tmp_path, monkeypatch, ["alpha?", "", "and alpha notes?", "/exit"])

    assert code == 0
    assert generator.histories == [[], ["alpha?"]]
    out = capsys.readouterr().out
    assert "Turn 1: see [1]." in out
    assert "Turn 2: see [1]." in out
    assert out.count("Sources:") == 2


def test_chat_reset_forgets_the_conversation(tmp_path, capsys, monkeypatch):
    generator, _ = _chat(tmp_path, monkeypatch, ["alpha?", "/reset", "alpha?"])

    assert generator.histories == [[], []]
    assert "Started a new conversation." in capsys.readouterr().out


def test_chat_ends_at_end_of_input(tmp_path, capsys, monkeypatch):
    generator, code = _chat(tmp_path, monkeypatch, [])

    assert code == 0
    assert generator.histories == []
    assert "/reset starts a new conversation" in capsys.readouterr().out


def test_language_and_length_flags_reach_the_settings(tmp_path, monkeypatch):
    import docsage.interfaces.cli as cli
    from docsage.container import Container

    seen = []

    def container(settings):
        seen.append(settings.answer_style)
        return Container(settings, _FakeGenerator())

    monkeypatch.setattr(cli, "Container", container)
    index = str(tmp_path / "index.json")

    main(["--index", index, "ask", "alpha?", "--language", "Portuguese", "--length", "short"])
    main(["--index", index, "report", "alpha?", "--length", "long", "-o", str(tmp_path / "r")])
    main(["--index", index, "ask", "alpha?"])

    assert [(style.language, style.length) for style in seen] == [
        ("Portuguese", "short"),
        ("", "long"),
        ("", "medium"),
    ]


def test_unknown_length_flag_is_rejected(tmp_path, capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["--index", str(tmp_path / "i.json"), "ask", "alpha?", "--length", "huge"])
    assert "invalid choice" in capsys.readouterr().err
