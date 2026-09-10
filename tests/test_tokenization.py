from travelmind.retrieval.tokenization import tokenize_for_lexical_search


def test_tokenizer_normalizes_ascii_and_emits_chinese_unigrams_and_bigrams() -> None:
    tokens = tokenize_for_lexical_search("故宫ＡI Route-7")

    assert {"故", "宫", "故宫", "ai", "route", "7"}.issubset(tokens)


def test_tokenizer_ignores_punctuation_only_input() -> None:
    assert tokenize_for_lexical_search("！？---") == []
