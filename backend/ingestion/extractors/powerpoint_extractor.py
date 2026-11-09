from __future__ import annotations

import io
from pathlib import Path
from typing import Any

try:
    from pptx import Presentation
except Exception:  # pragma: no cover - optional dependency
    Presentation = None

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class PowerPointExtractor(BaseExtractor):
    supported_extensions = (".pptx", ".pptm")

    def extract(
        self,
        *,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        if Presentation is None:
            return ExtractionResult(
                document_id=(metadata or {}).get("document_id", ""),
                filename=filename or "document.pptx",
                file_type="powerpoint",
                extracted_text="",
                sections=[],
                tables=[],
                metadata={"error": "python-pptx is not installed."},
                warnings=["PowerPoint extraction is unavailable because python-pptx is not installed."],
                extraction_status="warning",
            )

        if file_bytes is not None:
            presentation = Presentation(io.BytesIO(file_bytes))
        elif file_path is not None:
            presentation = Presentation(file_path)
        else:
            raise ValueError("PowerPoint extraction requires file bytes or a file path.")
        sections: list[ExtractionSection] = []
        texts: list[str] = []

        for slide_index, slide in enumerate(presentation.slides, start=1):
            texts_for_slide: list[str] = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    texts_for_slide.append(shape.text.strip())
                if getattr(shape, "has_table", False):
                    texts_for_slide.extend(
                        " | ".join(cell.text.strip() for cell in row.cells)
                        for row in shape.table.rows
                    )
            slide_text = "\n".join(texts_for_slide)
            texts.append(slide_text)
            if slide_text:
                sections.append(
                    ExtractionSection(
                        title=f"Slide {slide_index}",
                        text=slide_text,
                        section_type="slide",
                        order=slide_index,
                        metadata={"slide_number": slide_index},
                    )
                )

        extracted_text = "\n".join(texts)
        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.pptx",
            file_type="powerpoint",
            extracted_text=extracted_text,
            sections=sections,
            tables=[],
            metadata={"slide_count": len(presentation.slides)},
            warnings=[],
            extraction_status="completed",
        )
