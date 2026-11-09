from __future__ import annotations

from pathlib import Path
from typing import Any

from services.extraction_service import extract_document_content


def parse_uploaded_file(
    *,
    file_path: str | Path | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    document_id: str | None = None,
    metadata: dict[str, Any] | None = None,
):
    return extract_document_content(
        file_path=file_path,
        file_bytes=file_bytes,
        filename=filename,
        document_id=document_id,
        metadata=metadata,
    )
