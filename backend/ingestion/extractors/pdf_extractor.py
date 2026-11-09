from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class PdfExtractor(BaseExtractor):
    supported_extensions = (".pdf",)

    def extract(
        self,
        *,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        source = file_bytes
        if source is None and file_path is not None:
            source = Path(file_path).read_bytes()
        if source is None:
            raise ValueError("PDF extraction requires file bytes or a file path.")

        reader = PdfReader(io.BytesIO(source), strict=True)
        page_texts: list[str] = []
        warnings: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            page_texts.append(page_text)
            if not page_text:
                warnings.append(f"Page {page_number} contains no extractable text; it may be scanned or image-based.")

        extracted_text = "\n".join(page for page in page_texts if page).strip()
        sections = [
            ExtractionSection(
                title=f"Page {page_number}",
                text=page_text,
                page_number=page_number,
                section_type="page",
                order=page_number,
            )
            for page_number, page_text in enumerate(page_texts, start=1)
            if page_text
        ]

        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.pdf",
            file_type="pdf",
            extracted_text=extracted_text,
            sections=sections,
            tables=[],
            metadata={
                "page_count": len(page_texts),
                "page_texts": page_texts,
                "pages": len(page_texts),
                "pdf_metadata": dict(reader.metadata or {}),
            },
            warnings=warnings,
            extraction_status="completed" if extracted_text else "warning",
        )
