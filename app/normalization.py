import re

_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")


def normalize_lookup_text(value: str) -> str:
    lowered = value.strip().lower()
    without_punct = _PUNCT_RE.sub(" ", lowered)
    return _SPACE_RE.sub(" ", without_punct).strip()
