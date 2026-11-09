from __future__ import annotations

import email
from email import policy
from pathlib import Path
from typing import Any

from ingestion.base import BaseExtractor
from ingestion.models import ExtractionResult, ExtractionSection


class EmailExtractor(BaseExtractor):
    supported_extensions = (".eml",)

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
            raise ValueError("Email extraction requires file bytes or a file path.")

        message = email.message_from_bytes(file_bytes, policy=policy.default)
        body = ""
        if message.is_multipart():
            for part in message.iter_parts():
                if part.get_content_maintype() == "text":
                    body = part.get_content(); break
        else:
            body = message.get_content()

        sender = message.get("From", "")
        recipients = message.get("To", "")
        subject = message.get("Subject", "")
        date = message.get("Date", "")

        extracted_text = "\n".join(part for part in [subject, sender, recipients, body] if part)
        sections = [
            ExtractionSection(title="Email headers", text=f"Subject: {subject}\nFrom: {sender}\nTo: {recipients}\nDate: {date}", section_type="email", order=1),
            ExtractionSection(title="Email body", text=body, section_type="body", order=2),
        ]

        return ExtractionResult(
            document_id=(metadata or {}).get("document_id", ""),
            filename=filename or "document.eml",
            file_type="email",
            extracted_text=extracted_text,
            sections=sections,
            tables=[],
            metadata={"sender": sender, "recipients": recipients, "subject": subject, "date": date},
            warnings=[],
            extraction_status="completed",
        )
