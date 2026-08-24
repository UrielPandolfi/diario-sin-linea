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
