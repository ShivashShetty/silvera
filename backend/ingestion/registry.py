from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from .base import BaseExtractor


class ExtractionRegistry:
    def __init__(self) -> None:
        self._extractors: dict[str, BaseExtractor] = {}
        self._load_default_extractors()

    def _load_default_extractors(self) -> None:
        default_modules = [
            "ingestion.extractors.pdf_extractor",
            "ingestion.extractors.docx_extractor",
            "ingestion.extractors.excel_extractor",
            "ingestion.extractors.powerpoint_extractor",
            "ingestion.extractors.csv_extractor",
            "ingestion.extractors.text_extractor",
            "ingestion.extractors.html_extractor",
            "ingestion.extractors.email_extractor",
            "ingestion.extractors.json_extractor",
            "ingestion.extractors.xml_extractor",
        ]
        for module_name in default_modules:
            module = import_module(module_name)
            for _, candidate in vars(module).items():
                if isinstance(candidate, type) and issubclass(candidate, BaseExtractor) and candidate is not BaseExtractor:
                    extractor = candidate()
                    for suffix in extractor.supported_extensions:
                        self._extractors[suffix] = extractor

    def get(self, filename: str | None) -> BaseExtractor:
        if not filename:
            raise ValueError("Filename is required to select an extractor.")
        suffix = Path(filename).suffix.lower()
        extractor = self._extractors.get(suffix)
        if extractor is None:
            raise ValueError(f"No extraction strategy is registered for '{filename}'.")
        return extractor

    def extract(
        self,
        *,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        extractor = self.get(filename)
        result = extractor.extract(
            file_path=file_path,
            file_bytes=file_bytes,
            filename=filename,
            metadata=metadata,
        )
        if document_id and not result.document_id:
            result.document_id = document_id
        return result


def register_extractor(extractor: BaseExtractor) -> BaseExtractor:
    registry = _registry
    for suffix in extractor.supported_extensions:
        registry._extractors[suffix] = extractor
    return extractor


_registry = ExtractionRegistry()


def get_extractor_for_file(filename: str | None) -> BaseExtractor:
    return _registry.get(filename)


def extract_document(
    *,
    file_path: str | Path | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    document_id: str | None = None,
    metadata: dict[str, Any] | None = None,
):
    return _registry.extract(
        file_path=file_path,
        file_bytes=file_bytes,
        filename=filename,
        document_id=document_id,
        metadata=metadata,
    )
