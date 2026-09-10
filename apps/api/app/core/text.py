import hashlib
import re
import unicodedata


def normalize_name(value: str) -> str:
    collapsed = unicodedata.normalize("NFKD", value)
    collapsed = "".join(char for char in collapsed if not unicodedata.combining(char))
    collapsed = re.sub(r"\s+", " ", collapsed).strip().lower()
    return collapsed


def normalize_content(value: str) -> str:
    collapsed = unicodedata.normalize("NFKC", value)
    collapsed = re.sub(r"\s+", " ", collapsed).strip()
    return collapsed


_QUOTE_MAP = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u00ab": '"',
    "\u00bb": '"',
    "\u2018": "'",
    "\u2019": "'",
    "`": "'",
})


def normalize_excerpt(value: str) -> str:
    collapsed = normalize_content(value).translate(_QUOTE_MAP)
    return collapsed.casefold()


def excerpt_in_source(excerpt: str, *blobs: str | None) -> bool:
    needle = normalize_excerpt(excerpt)
    if not needle:
        return False
    haystack = normalize_excerpt(" ".join(part for part in blobs if part))
    return needle in haystack


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_fingerprint(*, title: str | None, body: str | None) -> str:
    parts = [normalize_content(title or ""), normalize_content(body or "")]
    material = "\n".join(part for part in parts if part)
    return sha256_text(material)


def token_set(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9áéíóúüñ]{3,}", value.lower())}


def name_tokens(value: str, *, min_len: int = 3) -> list[str]:
    return [token for token in normalize_name(value).split() if len(token) >= min_len]


def is_person_name_suffix(left: str, right: str) -> bool:
    """True if one PERSON name is a token suffix of the other (Bregman ⊂ Myriam Bregman)."""
    first, other = name_tokens(left), name_tokens(right)
    if not first or not other or first == other:
        return False
    if len(first) < len(other):
        return other[-len(first) :] == first
    if len(other) < len(first):
        return first[-len(other) :] == other
    return False


_PLACEHOLDER_VALUES = {"null", "none", "undefined", "nil", "n/a", "na", "unknown", "desconocido"}


def is_placeholder_text(value: str | None) -> bool:
    folded = normalize_name(value or "")
    if not folded:
        return True
    if folded in _PLACEHOLDER_VALUES:
        return True
    tokens = token_set(folded)
    return bool(tokens) and tokens <= _PLACEHOLDER_VALUES


def usable_text(*candidates: str | None) -> str:
    for raw in candidates:
        text = (raw or "").strip()
        if text and not is_placeholder_text(text):
            return text
    return ""


def postgres_safe_text(value: str | None) -> str | None:
    """Postgres text/varchar reject NUL bytes (e.g. fetched PDFs decoded as text)."""
    if value is None:
        return None
    cleaned = value.replace("\x00", "")
    return cleaned if cleaned else None


def postgres_safe_json(value):
    """Strip NUL bytes from nested JSON so jsonb columns can persist."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {key: postgres_safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [postgres_safe_json(item) for item in value]
    if isinstance(value, tuple):
        return [postgres_safe_json(item) for item in value]
    return value
