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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_fingerprint(*, title: str | None, body: str | None) -> str:
    parts = [normalize_content(title or ""), normalize_content(body or "")]
    material = "\n".join(part for part in parts if part)
    return sha256_text(material)


def token_set(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9áéíóúüñ]{3,}", value.lower())}
