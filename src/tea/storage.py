"""Token storage backends used by the OAuth client."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class TokenBundle(BaseModel):
    """Serializable representation of OAuth tokens."""

    access_token: Optional[str] = Field(default=None)
    refresh_token: Optional[str] = Field(default=None)
    expires_at: Optional[float] = Field(default=None, description="Epoch seconds when the token expires.")


class TokenStore(ABC):
    """Abstraction for persisting OAuth tokens."""

    @abstractmethod
    def load(self) -> TokenBundle:
        """Return the stored token bundle, defaulting to empty when no data exists."""

    @abstractmethod
    def save(self, bundle: TokenBundle) -> None:
        """Persist the provided token bundle."""


class MemoryTokenStore(TokenStore):
    """In-memory token store used for testing and mock scenarios."""

    def __init__(self, initial: Optional[TokenBundle] = None) -> None:
        self._bundle = initial or TokenBundle()

    def load(self) -> TokenBundle:
        return self._bundle.model_copy(deep=True)

    def save(self, bundle: TokenBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)


class FileTokenStore(TokenStore):
    """Persist tokens to disk as JSON, supporting bind-mounted secret stores."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> TokenBundle:
        if not self._path.exists():
            return TokenBundle()
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return TokenBundle.model_validate(data)

    def save(self, bundle: TokenBundle) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(bundle.model_dump_json(), encoding="utf-8")
