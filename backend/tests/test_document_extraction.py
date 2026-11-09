import io
import unittest

from docx import Document
from openpyxl import Workbook
from pptx import Presentation

from services.document_extraction import (
    DocumentExtractionError,
    extract_non_pdf,
)


class DocumentExtractionTests(unittest.TestCase):
    def test_text_and_structured_text_formats(self):
        examples = {
            "notes.txt": (b"Quarterly plan", "plan"),
            "notes.md": (b"# Quarterly plan", "plan"),
            "table.csv": (b"name,value\nRevenue,42", "42"),
            "table.tsv": (b"name\tvalue\nRevenue\t42", "42"),
            "page.html": (b"<h1>Quarterly plan</h1><script>do not index</script>", "plan"),
            "data.json": (b'{"revenue": 42}', "42"),
            "data.xml": (b"<root><revenue>42</revenue></root>", "42"),
            "message.eml": (
                b"Subject: Plan\nContent-Type: text/plain; charset=utf-8\n\nQuarterly plan",
                "plan",
            ),
        }
        for filename, (content, expected) in examples.items():
            with self.subTest(filename=filename):
                pages = extract_non_pdf(filename, content)
                self.assertTrue(pages)
                self.assertIn(expected, "\n".join(pages).lower())
        self.assertNotIn(
            "do not index",
            "\n".join(extract_non_pdf("page.html", examples["page.html"][0])),
        )

    def test_office_formats_extract_text_by_section(self):
        document = Document()
        document.add_paragraph("Word policy")
        docx_content = io.BytesIO()
        document.save(docx_content)

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Sales"
        worksheet.append(["Revenue", 42])
        xlsx_content = io.BytesIO()
        workbook.save(xlsx_content)

        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        shape = slide.shapes.add_textbox(0, 0, 500, 100)
        shape.text = "Quarterly update"
        pptx_content = io.BytesIO()
        presentation.save(pptx_content)

        self.assertIn(
            "Word policy",
            extract_non_pdf("policy.docx", docx_content.getvalue())[0],
        )
        self.assertIn(
            "Revenue | 42",
            extract_non_pdf("sales.xlsx", xlsx_content.getvalue())[0],
        )
        self.assertIn(
            "Quarterly update",
            extract_non_pdf("update.pptx", pptx_content.getvalue())[0],
        )

    def test_invalid_or_unsupported_documents_are_reported(self):
        for filename, content in (
            ("bad.docx", b"not a zip file"),
            ("unsupported.bin", b"text"),
            ("empty.txt", b"   "),
            ("entities.xml", b"<!DOCTYPE root [<!ENTITY x 'unsafe'>]><root>&x;</root>"),
        ):
            with self.subTest(filename=filename):
                with self.assertRaises(DocumentExtractionError):
                    extract_non_pdf(filename, content)

    def test_large_csv_exceeds_the_old_two_million_character_limit(self):
        content = b"revenue\n" + b"1" * 2_100_000
        pages = extract_non_pdf("large-sales.csv", content)
        self.assertGreater(len(pages[0]), 2_000_000)


if __name__ == "__main__":
    unittest.main()
