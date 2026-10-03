from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def prompt_version(filename: str) -> str:
    import hashlib

    return hashlib.sha256(load_prompt(filename).encode("utf-8")).hexdigest()[:16]
