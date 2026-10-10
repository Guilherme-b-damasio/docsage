from docsage.infrastructure.highlighting import TermHighlighter
from docsage.infrastructure.tokenizer import Tokenizer, multilingual_tokenizer


def spans(text, highlights):
    return [(text[item.start : item.end], item.term) for item in highlights]


def test_marks_each_occurrence_ignoring_case():
    text = "The Index is saved; the index is loaded."

    highlights = TermHighlighter(multilingual_tokenizer()).highlight("index", text)

    assert spans(text, highlights) == [("Index", "index"), ("index", "index")]
    assert [item.start for item in highlights] == [4, 24]


def test_query_stopwords_never_match():
    text = "What is the capital of France?"

    highlights = TermHighlighter(multilingual_tokenizer()).highlight("what is the capital", text)

    assert spans(text, highlights) == [("capital", "capital")]


def test_whole_words_only():
    text = "indexing an index"

    highlights = TermHighlighter(Tokenizer()).highlight("index", text)

    assert spans(text, highlights) == [("index", "index")]


def test_non_ascii_words_keep_their_offsets():
    text = "Configuração rápida: a configuração fica no arquivo."

    highlights = TermHighlighter(multilingual_tokenizer()).highlight("CONFIGURAÇÃO", text)

    assert spans(text, highlights) == [
        ("Configuração", "configuração"),
        ("configuração", "configuração"),
    ]


def test_query_without_terms_highlights_nothing():
    assert TermHighlighter(multilingual_tokenizer()).highlight("the of", "the end of it") == []
