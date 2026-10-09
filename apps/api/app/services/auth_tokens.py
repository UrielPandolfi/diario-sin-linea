"""Hash de tokens de un solo uso. El valor en claro solo viaja en el enlace."""

from __future__ import annotations

import hashlib


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
