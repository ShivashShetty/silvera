from __future__ import annotations

import io
from pathlib import Path
from typing import Any

try:
    from docx import Document
except Exception:  # pragma: no cover - optional dependency
    Document = None

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class DocxExtractor(BaseExtractor):
    supported_extensions = (".docx", ".docm")

    def extract(
        self,
        *,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        if Document is None:
            return ExtractionResult(
                document_id=(metadata or {}).get("document_id", ""),
                filename=filename or "document.docx",
                file_type="docx",
                extracted_text="",
                sections=[],
                tables=[],
                metadata={"error": "python-docx is not installed."},
                warnings=["Word extraction is unavailable because python-docx is not installed."],
                extraction_status="warning",
            )

        if file_bytes is not None:
            doc = Document(io.BytesIO(file_bytes))
        elif file_path is not None:
            doc = Document(file_path)
        else:
            raise ValueError("Word extraction requires file bytes or a file path.")
        lines: list[str] = []
        sections: list[ExtractionSection] = []
        order = 0
        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            text = paragraph.text.strip()
            if not text:
                continue
            order += 1
            lines.append(text)
            sections.append(
                ExtractionSection(
                    title=f"Paragraph {paragraph_index}",
                    text=text,
                    section_type="paragraph",
                    order=order,
                )
            )

        for table_index, table in enumerate(doc.tables, start=1):
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            table_text = "\n".join(" | ".join(row) for row in rows)
            if table_text:
                order += 1
                lines.append(table_text)
                sections.append(
                    ExtractionSection(
                        title=f"Table {table_index}",
                        text=table_text,
                        section_type="table",
                        order=order,
                        metadata={"rows": rows},
                    )
                )

        extracted_text = "\n".join(lines)
        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.docx",
            file_type="docx",
            extracted_text=extracted_text,
            sections=sections,
            tables=[{"rows": [[cell.text for cell in row.cells] for table in doc.tables for row in table.rows]}],
            metadata={"paragraph_count": len(doc.paragraphs), "table_count": len(doc.tables)},
            warnings=[],
            extraction_status="completed",
        )
