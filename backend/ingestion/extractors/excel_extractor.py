from __future__ import annotations

import io
from pathlib import Path
from typing import Any

try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover - optional dependency
    load_workbook = None

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class ExcelExtractor(BaseExtractor):
    supported_extensions = (".xlsx", ".xlsm")

    def extract(
        self,
        *,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        if load_workbook is None:
            return ExtractionResult(
                document_id=(metadata or {}).get("document_id", ""),
                filename=filename or "document.xlsx",
                file_type="excel",
                extracted_text="",
                sections=[],
                tables=[],
                metadata={"error": "openpyxl is not installed."},
                warnings=["Spreadsheet extraction is unavailable because openpyxl is not installed."],
                extraction_status="warning",
            )

        if file_bytes is not None:
            workbook = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        elif file_path is not None:
            workbook = load_workbook(file_path, read_only=True, data_only=True)
        else:
            raise ValueError("Spreadsheet extraction requires file bytes or a file path.")
        tables: list[dict[str, Any]] = []
        sections: list[ExtractionSection] = []
        lines: list[str] = []

        for sheet_index, worksheet in enumerate(workbook.worksheets, start=1):
            rows = list(worksheet.iter_rows(values_only=True))
            if not rows:
                continue
            headers = [str(item) if item is not None else "" for item in rows[0]]
            table_rows = [list(row) for row in rows[1:]]
            table = {"sheet_name": worksheet.title, "headers": headers, "rows": table_rows}
            tables.append(table)
            sheet_lines = [f"Sheet: {worksheet.title}", ", ".join(headers)]
            for row_index, row in enumerate(table_rows, start=2):
                values = ", ".join(str(value) if value is not None else "" for value in row)
                sheet_lines.append(f"Row {row_index}: {values}")

            for batch_start in range(0, len(sheet_lines), 50):
                batch = sheet_lines[batch_start : batch_start + 50]
                section_order = len(sections) + 1
                sections.append(
                    ExtractionSection(
                        title=f"{worksheet.title} — section {section_order}",
                        text="\n".join(batch),
                        section_type="table",
                        order=section_order,
                        metadata={
                            "sheet_name": worksheet.title,
                            "section_number": section_order,
                            "row_count": len(batch),
                            "headers": headers,
                        },
                    )
                )
                lines.extend(batch)

        extracted_text = "\n".join(lines)
        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.xlsx",
            file_type="excel",
            extracted_text=extracted_text,
            sections=sections,
            tables=tables,
            metadata={"sheet_count": len(workbook.worksheets), "sheets": [sheet.title for sheet in workbook.worksheets]},
            warnings=[],
            extraction_status="completed",
        )
