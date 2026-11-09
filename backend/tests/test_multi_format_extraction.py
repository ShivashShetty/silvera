import io
import unittest

from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from ingestion.registry import extract_document


class MultiFormatExtractionTests(unittest.TestCase):
    def test_text_extractor_handles_plain_text(self):
        result = extract_document(file_bytes=b"Alpha beta\nGamma delta", filename="notes.txt")
        self.assertEqual(result.file_type, "text")
        self.assertIn("Alpha beta", result.extracted_text)

    def test_csv_extractor_preserves_table_rows(self):
        result = extract_document(file_bytes=b"name,age\nAda,42\nGrace,37\n", filename="people.csv")
        self.assertEqual(result.file_type, "csv")
        self.assertEqual(result.tables[0]["headers"], ["name", "age"])
        self.assertEqual(result.tables[0]["rows"][0], ["Ada", "42"])

    def test_csv_content_is_available_across_multiple_sections(self):
        rows = ["name,age"] + [f"person-{index},{index}" for index in range(60)]
        result = extract_document(
            file_bytes="\n".join(rows).encode(),
            filename="people.csv",
        )
        self.assertEqual(len(result.sections), 2)
        self.assertIn("person-59", result.sections[-1].text)

    def test_json_extractor_handles_nested_data(self):
        payload = b'{"employees": [{"name": "Ada", "department": "Engineering"}]}'
        result = extract_document(file_bytes=payload, filename="employees.json")
        self.assertEqual(result.file_type, "json")
        self.assertIn("Ada", result.extracted_text)

    def test_docx_extractor_reads_uploaded_bytes(self):
        document = Document()
        document.add_heading("Benefits", level=1)
        document.add_paragraph("Employees receive annual leave.")
        output = io.BytesIO()
        document.save(output)

        result = extract_document(file_bytes=output.getvalue(), filename="benefits.docx")
        self.assertIn("Employees receive annual leave.", result.extracted_text)
        self.assertTrue(result.sections)

    def test_xlsx_extractor_preserves_sheet_data_and_sections(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Sales"
        worksheet.append(["product", "revenue"])
        for index in range(60):
            worksheet.append([f"item-{index}", index * 10])
        output = io.BytesIO()
        workbook.save(output)

        result = extract_document(file_bytes=output.getvalue(), filename="sales.xlsx")
        self.assertEqual(result.tables[0]["sheet_name"], "Sales")
        self.assertEqual(len(result.tables[0]["rows"]), 60)
        self.assertGreaterEqual(len(result.sections), 2)
        self.assertIn("item-59", result.extracted_text)

    def test_powerpoint_extractor_reads_uploaded_bytes(self):
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        textbox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        textbox.text = "Quarterly results"
        output = io.BytesIO()
        presentation.save(output)

        result = extract_document(file_bytes=output.getvalue(), filename="results.pptx")
        self.assertIn("Quarterly results", result.extracted_text)


if __name__ == "__main__":
    unittest.main()
