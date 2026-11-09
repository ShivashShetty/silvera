from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class XmlExtractor(BaseExtractor):
    supported_extensions = (".xml",)

    def _iter_text(self, element: ET.Element, prefix: str = "") -> list[str]:
        items: list[str] = []
        if element.text and element.text.strip():
            items.append(f"{prefix}{element.tag}: {element.text.strip()}")
        for child in element:
            items.extend(self._iter_text(child, f"{prefix}{element.tag}/"))
        return items

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
            raise ValueError("XML extraction requires file bytes or a file path.")

        try:
            root = ET.fromstring(file_bytes.decode("utf-8", errors="replace"))
        except ET.ParseError as exc:
            raise ValueError(f"Could not parse XML: {exc}") from exc

        lines = self._iter_text(root)
        extracted_text = "\n".join(lines)
        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.xml",
            file_type="xml",
            extracted_text=extracted_text,
            sections=[
                ExtractionSection(
                    title="XML content",
                    text=extracted_text,
                    section_type="xml",
                    order=1,
                    metadata={"root": root.tag},
                )
            ],
            tables=[],
            metadata={"root_tag": root.tag},
            warnings=[],
            extraction_status="completed",
        )
