from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .models import ExtractionResult


class BaseExtractor(ABC):
    """Base interface for a document-specific extractor."""

    supported_extensions: tuple[str, ...] = ()

    @classmethod
    def supports(cls, filename: str | None) -> bool:
        if not filename:
            return False
        suffix = Path(filename).suffix.lower()
        return suffix in cls.supported_extensions

    @abstractmethod
    def extract(
        self,
        *,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Return normalized extracted content for a single file."""
        raise NotImplementedError
