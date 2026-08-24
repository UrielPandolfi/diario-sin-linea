from app.core.config import get_settings
from app.core.db import engine

settings = get_settings()
__all__ = ["engine", "settings"]
