import csv
import io
import json
import re
import zipfile
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation


SUPPORTED_EXTENSIONS = {
    ".docm",
    ".docx",
    ".csv",
    ".eml",
    ".htm",
    ".html",
    ".json",
    ".md",
    ".pptm",
    ".pptx",
    ".tsv",
    ".txt",
    ".xlsm",
    ".xlsx",
    ".xml",
}
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 5000
MAX_EXTRACTED_CHARACTERS = 50_000_000
MAX_DOCUMENT_SECTIONS = 500


class DocumentExtractionError(ValueError):
    pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "template"}:
            self.hidden_depth += 1
        elif tag.lower() in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "template"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag.lower() in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _validate_archive(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise DocumentExtractionError("The Office document is not a valid file.") from exc
    if len(entries) > MAX_ARCHIVE_ENTRIES or sum(
        entry.file_size for entry in entries
    ) > MAX_ARCHIVE_BYTES:
        raise DocumentExtractionError("The Office document expands beyond the supported size.")


def _clean_pages(pages: Iterable[str]) -> list[str]:
    cleaned = ["\n".join(line.rstrip() for line in page.splitlines()).strip() for page in pages]
    cleaned = [page for page in cleaned if page]
    if not cleaned:
        raise DocumentExtractionError("No readable text was found in this document.")
    if len(cleaned) > MAX_DOCUMENT_SECTIONS:
        raise DocumentExtractionError("The document has too many sections to index.")
    if sum(map(len, cleaned)) > MAX_EXTRACTED_CHARACTERS:
        raise DocumentExtractionError("The extracted text exceeds the supported size.")
    return cleaned


def _extract_docx(content: bytes) -> list[str]:
    _validate_archive(content)
    document = Document(io.BytesIO(content))
    lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return _clean_pages(["\n".join(lines)])


def _extract_spreadsheet(content: bytes) -> list[str]:
    _validate_archive(content)
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        if len(workbook.worksheets) > MAX_DOCUMENT_SECTIONS:
            raise DocumentExtractionError("The document has too many sections to index.")
        sheets = []
        total_characters = 0
        for worksheet in workbook.worksheets:
            lines = [f"Sheet: {worksheet.title}"]
            total_characters += len(lines[0])
            for row in worksheet.iter_rows(values_only=True):
                values = ["" if value is None else str(value) for value in row]
                if any(values):
                    line = " | ".join(values)
                    total_characters += len(line) + 1
                    if total_characters > MAX_EXTRACTED_CHARACTERS:
                        raise DocumentExtractionError(
                            "The extracted text exceeds the supported size."
                        )
                    lines.append(line)
            sheets.append("\n".join(lines))
        return _clean_pages(sheets)
    finally:
        workbook.close()


def _extract_delimited_text(content: bytes, delimiter: str) -> list[str]:
    text = content.decode("utf-8-sig")
    lines = []
    character_count = 0
    previous_field_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(MAX_EXTRACTED_CHARACTERS)
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            line = " | ".join(row)
            character_count += len(line) + 1
            if character_count > MAX_EXTRACTED_CHARACTERS:
                raise DocumentExtractionError(
                    "The extracted text exceeds the supported size of 50 million characters."
                )
            lines.append(line)
    finally:
        csv.field_size_limit(previous_field_limit)
    return _clean_pages(["\n".join(lines)])


def _extract_presentation(content: bytes) -> list[str]:
    _validate_archive(content)
    presentation = Presentation(io.BytesIO(content))
    slides = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        lines = [f"Slide {slide_number}"]
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                lines.extend(
                    paragraph.text
                    for paragraph in shape.text_frame.paragraphs
                    if paragraph.text.strip()
                )
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        slides.append("\n".join(lines))
    return _clean_pages(slides)


def extract_non_pdf(filename: str, content: bytes) -> list[str]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise DocumentExtractionError(
            f"Unsupported file type. Supported types are PDF and: {supported}."
        )

    try:
        if extension in {".docx", ".docm"}:
            return _extract_docx(content)
        if extension in {".xlsx", ".xlsm"}:
            return _extract_spreadsheet(content)
        if extension in {".pptx", ".pptm"}:
            return _extract_presentation(content)
        if extension in {".txt", ".md"}:
            text = content.decode("utf-8-sig")
            if len(text) > MAX_EXTRACTED_CHARACTERS:
                raise DocumentExtractionError(
                    "The extracted text exceeds the supported size of 50 million characters."
                )
            return _clean_pages([text])
        if extension in {".csv", ".tsv"}:
            return _extract_delimited_text(
                content,
                delimiter="\t" if extension == ".tsv" else ",",
            )
        if extension in {".html", ".htm"}:
            parser = _VisibleTextParser()
            parser.feed(content.decode("utf-8-sig"))
            parser.close()
            return _clean_pages(["".join(parser.parts)])
        if extension == ".eml":
            message = BytesParser(policy=policy.default).parsebytes(content)
            parts = []
            for part in message.walk():
                if (
                    part.get_content_type() == "text/plain"
                    and part.get_content_disposition() != "attachment"
                ):
                    text = part.get_content()
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
            return _clean_pages(["\n".join(parts)])
        if extension == ".json":
            value = json.loads(content.decode("utf-8-sig"))
            return _clean_pages([json.dumps(value, ensure_ascii=False, indent=2)])
        if extension == ".xml":
            if re.search(rb"<!DOCTYPE|<!ENTITY", content, re.IGNORECASE):
                raise DocumentExtractionError(
                    "XML documents with DTD or entity declarations are not supported."
                )
            root = ElementTree.fromstring(content)
            return _clean_pages(["\n".join(text.strip() for text in root.itertext() if text.strip())])
    except DocumentExtractionError:
        raise
    except (UnicodeDecodeError, csv.Error, json.JSONDecodeError, ElementTree.ParseError) as exc:
        raise DocumentExtractionError("Could not read the document's text content.") from exc
    except Exception as exc:
        raise DocumentExtractionError("Could not read this document. Check that the file is valid.") from exc

    raise DocumentExtractionError("Unsupported file type.")
