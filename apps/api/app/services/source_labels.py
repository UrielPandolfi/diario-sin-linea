"""Etiquetas públicas de fuentes. No altera la URL ni los datos guardados."""

from __future__ import annotations

_HOST_PREFIXES = ("www.", "staging.", "stage.", "dev.", "preview.", "beta.", "test.")


def _looks_like_host(value: str) -> bool:
    return " " not in value and "." in value and "@" not in value


def public_source_name(name: str | None, domain: str | None) -> str:
    raw = (name or "").strip() or (domain or "").strip()
    if not raw:
        return "Publicación"
    if not _looks_like_host(raw):
        return raw
    label = raw.casefold()
    for prefix in _HOST_PREFIXES:
        if label.startswith(prefix):
            rest = label[len(prefix) :]
            if "." in rest:
                label = rest
            break
    return label


def public_source_title(title: str | None) -> str | None:
    text = (title or "").strip()
    if not text or not _legible(text):
        return None
    return text


def _legible(text: str) -> bool:
    if any(ord(char) < 32 for char in text):
        return False
    letters = sum(1 for char in text if char.isalpha())
    return letters > 0 and letters / len(text) >= 0.6
