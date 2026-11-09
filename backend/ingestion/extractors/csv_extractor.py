from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class CsvExtractor(BaseExtractor):
    supported_extensions = (".csv", ".tsv")

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
            raise ValueError("CSV extraction requires file bytes or a file path.")

        delimiter = "," if Path(filename or "").suffix.lower() == ".csv" else "\t"
        reader = csv.reader(io.StringIO(file_bytes.decode("utf-8", errors="replace")), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return ExtractionResult(
                document_id=(metadata or {}).get("document_id", ""),
                filename=filename or "document.csv",
                file_type="csv",
                extracted_text="",
                sections=[],
                tables=[],
                metadata={"delimiter": delimiter, "rows": 0},
                warnings=["The uploaded CSV/TSV file is empty."],
                extraction_status="warning",
            )

        headers = rows[0]
        table_rows = rows[1:]
        table = {
            "headers": headers,
            "rows": table_rows,
            "row_count": len(table_rows),
            "column_count": len(headers),
        }

        sections: list[ExtractionSection] = []
        for batch_start in range(0, len(table_rows) or 1, 50):
            batch_rows = table_rows[batch_start : batch_start + 50]
            section_order = len(sections) + 1
            section_text = "\n".join(
                [", ".join(headers)]
                + [
                    f"Row {batch_start + row_index + 2}: {', '.join(row)}"
                    for row_index, row in enumerate(batch_rows)
                ]
            )
            sections.append(
                ExtractionSection(
                    title=f"CSV rows {batch_start + 1}-{batch_start + len(batch_rows)}",
                    text=section_text,
                    section_type="table",
                    order=section_order,
                    metadata={
                        "headers": headers,
                        "row_start": batch_start + 1,
                        "row_count": len(batch_rows),
                    },
                )
            )

        extracted_text = "\n".join(section.text for section in sections)
        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.csv",
            file_type="csv",
            extracted_text=extracted_text,
            sections=sections,
            tables=[table],
            metadata={"delimiter": delimiter, "rows": len(rows), "columns": len(headers)},
            warnings=[],
            extraction_status="completed",
        )
