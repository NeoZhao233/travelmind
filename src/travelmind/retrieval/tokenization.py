import re
import unicodedata

_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9]+")


def tokenize_for_lexical_search(text: str) -> list[str]:
    """Tokenize Chinese into unigrams/bigrams and keep lowercase ASCII terms.

    This is intentionally deterministic and dependency-free. It is a BM25 baseline, not a claim
    that character n-grams are the best Chinese segmentation strategy.
    """

    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        value = match.group()
        if "\u4e00" <= value[0] <= "\u9fff":
            tokens.extend(value)
            tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
        else:
            tokens.append(value)
    return tokens
