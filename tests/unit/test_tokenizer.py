from docsage.infrastructure.tokenizer import (
    ENGLISH_STOPWORDS,
    PORTUGUESE_STOPWORDS,
    Tokenizer,
    multilingual_tokenizer,
)


def test_tokenizer_without_stopwords_keeps_every_word():
    assert Tokenizer()("The cat, the HAT!") == ["the", "cat", "the", "hat"]


def test_tokenizer_drops_stopwords_case_insensitively():
    assert Tokenizer({"The"})("The cat and the hat") == ["cat", "and", "hat"]


def test_multilingual_tokenizer_drops_english_and_portuguese_stopwords():
    tokenize = multilingual_tokenizer()
    assert tokenize("What is the capital of France?") == ["capital", "france"]
    assert tokenize("Qual é a capital da França?") == ["capital", "frança"]


def test_stopword_lists_are_lowercase():
    for word in ENGLISH_STOPWORDS | PORTUGUESE_STOPWORDS:
        assert word == word.lower()
