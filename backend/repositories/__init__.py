import os

from .base import Repository, RepositoryError
from .memory import MemoryRepository


def make_repository(url: str | None = None) -> Repository:
    """In-memory by default; PostgreSQL when CD_DATABASE_URL (or ``url``) is set."""
    url = url or os.environ.get("CD_DATABASE_URL")
    if not url:
        return MemoryRepository()
    from .sql import SqlRepository  # imported lazily: needs a PostgreSQL driver

    return SqlRepository(url)


__all__ = ["Repository", "RepositoryError", "MemoryRepository", "make_repository"]
