import re
import unicodedata
from uuid import uuid4


def slugify(value: str, *, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    slug = slug[:max_length].strip("-")
    return slug or "suceso"


def unique_suffix() -> str:
    return uuid4().hex[:8]
