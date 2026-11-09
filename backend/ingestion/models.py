from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractionSection:
    title: str | None = None
    text: str = ""
    page_number: int | None = None
    heading: str | None = None
    section_type: str = "text"
    order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    document_id: str
    filename: str
    file_type: str
    extracted_text: str
    sections: list[ExtractionSection] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    extraction_status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "extracted_text": self.extracted_text,
            "sections": [
                {
                    "title": section.title,
                    "text": section.text,
                    "page_number": section.page_number,
                    "heading": section.heading,
                    "section_type": section.section_type,
                    "order": section.order,
                    "metadata": section.metadata,
                }
                for section in self.sections
            ],
            "tables": self.tables,
            "metadata": self.metadata,
            "warnings": self.warnings,
            "extraction_status": self.extraction_status,
        }
