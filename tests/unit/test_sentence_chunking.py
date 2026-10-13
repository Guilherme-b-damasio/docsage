import pytest

from docsage.domain.models import Document
from docsage.infrastructure.chunking import SentenceChunker, sentence_spans


def sentences(text: str) -> list[str]:
    return [" ".join(word.group() for word in sentence) for sentence in sentence_spans(text)]


def chunk_texts(text: str, size: int, overlap: int = 0) -> list[str]:
    document = Document(source="a.txt", text=text)
    return [chunk.text for chunk in SentenceChunker(size, overlap).split(document)]


def test_splits_on_terminal_punctuation():
    assert sentences("One two. Three four! Five six? Seven…") == [
        "One two.",
        "Three four!",
        "Five six?",
        "Seven…",
    ]


def test_keeps_abbreviations_and_lower_case_continuations_together():
    text = "See e.g. the guide. It has fig. 3 and costs approx. ten euros. Version 3.11 works."
    assert sentences(text) == [
        "See e.g. the guide.",
        "It has fig. 3 and costs approx. ten euros.",
        "Version 3.11 works.",
    ]


def test_closing_quotes_and_brackets_still_end_a_sentence():
    assert sentences('He said "stop." Then (quietly.) "Go on."') == [
        'He said "stop."',
        "Then (quietly.)",
        '"Go on."',
    ]


def test_blank_lines_end_a_sentence_even_without_punctuation():
    assert sentences("# Install\n\nRun pip\r\n\r\n- item one\n- item two") == [
        "# Install",
        "Run pip",
        "- item one - item two",
    ]


def test_packs_whole_sentences_up_to_the_size():
    text = "A b c. D e. F g h i. J."
    assert chunk_texts(text, size=5) == ["A b c. D e.", "F g h i. J."]


def test_overlap_repeats_the_last_sentences_that_fit():
    text = "A b. C d. E f. G h."
    assert chunk_texts(text, size=4, overlap=2) == ["A b. C d.", "C d. E f.", "E f. G h."]


def test_overlap_never_repeats_a_whole_chunk():
    # The first sentence fits in the overlap too, but carrying it would repeat the chunk.
    text = "A b c. D. E f g."
    assert chunk_texts(text, size=4, overlap=3) == ["A b c. D.", "D. E f g."]


def test_long_sentences_are_cut_into_windows():
    text = "one two three four five six seven. End."
    assert chunk_texts(text, size=3) == ["one two three", "four five six", "seven. End."]


def test_chunks_carry_ids_positions_and_pages():
    text = "First page sentence. Second page sentence."
    document = Document(source="a.pdf", text=text, page_offsets=(0, text.index("Second")))

    chunks = SentenceChunker(size=3, overlap=0).split(document)

    assert [chunk.position for chunk in chunks] == [0, 1]
    assert len({chunk.id for chunk in chunks}) == 2
    assert [(chunk.first_page, chunk.last_page) for chunk in chunks] == [(1, 1), (2, 2)]


def test_empty_document_yields_no_chunks():
    assert SentenceChunker().split(Document(source="e.txt", text="  \n ")) == []


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (5, 5), (5, -1)])
def test_invalid_configuration_is_rejected(size, overlap):
    with pytest.raises(ValueError):
        SentenceChunker(size=size, overlap=overlap)
