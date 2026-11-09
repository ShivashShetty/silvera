from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sections: list[tuple[str, str]] = []
        self.current_heading: list[str] = []
        self.current_paragraph: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.current_heading = []
        elif tag == "p":
            self.current_paragraph = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.current_heading:
            text = " ".join(self.current_heading).strip()
            if text:
                self.sections.append(("heading", text))
            self.current_heading = []
        elif tag == "p" and self.current_paragraph:
            text = " ".join(self.current_paragraph).strip()
            if text:
                self.sections.append(("paragraph", text))
            self.current_paragraph = []

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self.current_heading:
            self.current_heading.append(text)
        elif self.current_paragraph:
            self.current_paragraph.append(text)
        else:
            self.sections.append(("text", text))

    def get_sections(self) -> list[tuple[str, str]]:
        return self.sections


class HtmlExtractor(BaseExtractor):
    supported_extensions = (".html", ".htm")

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
            raise ValueError("HTML extraction requires file bytes or a file path.")

        text = file_bytes.decode("utf-8", errors="replace")
        parser = _HtmlTextExtractor()
        parser.feed(text)
        parser.close()

        sections = [
            ExtractionSection(
                title=section_type,
                text=value,
                section_type=section_type,
                order=index + 1,
            )
            for index, (section_type, value) in enumerate(parser.get_sections())
            if value
        ]
        extracted_text = "\n".join(section.text for section in sections)

        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.html",
            file_type="html",
            extracted_text=extracted_text,
            sections=sections,
            tables=[],
            metadata={"source": "html_parser"},
            warnings=[],
            extraction_status="completed",
        )
