from __future__ import annotations

from pathlib import Path
from typing import Any

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class TextExtractor(BaseExtractor):
    supported_extensions = (".txt", ".md", ".tsv", ".log")

    def extract(
        self,
        *,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        if file_bytes is None and file_path is not None:
            file_bytes = Path(file_path).read_bytes()

        if file_bytes is None:
            raise ValueError("Text extraction requires file bytes or a file path.")

        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("utf-8", errors="replace")

        chunks = [chunk.strip() for chunk in text.splitlines() if chunk.strip()]
        sections = [
            ExtractionSection(
                title=f"Text block {index}",
                text=chunk,
                section_type="text",
                order=index,
            )
            for index, chunk in enumerate(chunks, start=1)
            if chunk
        ]

        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.txt",
            file_type="text",
            extracted_text=text.strip(),
            sections=sections,
            tables=[],
            metadata={"content_type": "text/plain"},
            warnings=[],
            extraction_status="completed",
        )
