from __future__ import annotations

from pathlib import Path
from typing import Any

from ingestion.registry import extract_document


def extract_document_content(
    *,
    file_path: str | Path | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    document_id: str | None = None,
    metadata: dict[str, Any] | None = None,
):
    return extract_document(
        file_path=file_path,
        file_bytes=file_bytes,
        filename=filename,
        document_id=document_id,
        metadata=metadata,
    )
