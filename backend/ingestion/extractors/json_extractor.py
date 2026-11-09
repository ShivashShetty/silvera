from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class JsonExtractor(BaseExtractor):
    supported_extensions = (".json",)

    def _flatten(self, value: Any, prefix: str = "") -> list[str]:
        if isinstance(value, dict):
            lines: list[str] = []
            for key, nested in value.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                lines.extend(self._flatten(nested, path))
            return lines
        if isinstance(value, list):
            lines: list[str] = []
            for index, item in enumerate(value):
                path = f"{prefix}[{index}]" if prefix else f"[{index}]"
                lines.extend(self._flatten(item, path))
            return lines
        if prefix:
            return [f"{prefix}: {value}"]
        return [str(value)]

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
            raise ValueError("JSON extraction requires file bytes or a file path.")

        try:
            payload = json.loads(file_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not parse JSON: {exc}") from exc

        lines = self._flatten(payload)
        extracted_text = "\n".join(lines)
        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.json",
            file_type="json",
            extracted_text=extracted_text,
            sections=[
                ExtractionSection(
                    title="JSON content",
                    text=extracted_text,
                    section_type="json",
                    order=1,
                    metadata={"keys": list(lines)[:10]},
                )
            ],
            tables=[],
            metadata={"json_type": type(payload).__name__},
            warnings=[],
            extraction_status="completed",
        )
