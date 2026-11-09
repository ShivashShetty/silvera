import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from services import structured_data_service as structured


class StructuredDataServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "structured_data.db"
        self.path_patch = patch.object(
            structured, "STRUCTURED_DB_PATH", self.database_path
        )
        self.path_patch.start()
        self.document_id = str(uuid4())
        self.datasets = structured.index_structured_document(
            self.document_id,
            "sales.csv",
            [
                {
                    "headers": ["Region", "Revenue"],
                    "rows": [["West", "100"], ["East", "200"], ["West", "50"]],
                }
            ],
        )

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_select_query_returns_results_and_metadata(self):
        table_name = self.datasets[0]["table_name"]
        columns, rows, truncated, _ = structured._execute_read_only(
            f'SELECT "region", SUM("revenue") AS total FROM "{table_name}" GROUP BY "region" ORDER BY total DESC',
            {table_name},
        )
        self.assertEqual(columns, ["region", "total"])
        self.assertEqual(rows, [["East", 200], ["West", 150]])
        self.assertFalse(truncated)

    def test_write_queries_are_rejected(self):
        table_name = self.datasets[0]["table_name"]
        with self.assertRaises(structured.StructuredQueryError):
            structured._execute_read_only(
                f'DELETE FROM "{table_name}"', {table_name}
            )

    def test_queries_cannot_read_other_tables(self):
        table_name = self.datasets[0]["table_name"]
        with self.assertRaises(structured.StructuredQueryError):
            structured._execute_read_only(
                "SELECT name FROM sqlite_master", {table_name}
            )

    def test_queries_must_use_uploaded_data(self):
        table_name = self.datasets[0]["table_name"]
        with self.assertRaises(structured.StructuredQueryError):
            structured._execute_read_only("SELECT 1", {table_name})

    def test_multiple_statements_are_rejected(self):
        table_name = self.datasets[0]["table_name"]
        with self.assertRaises(structured.StructuredQueryError):
            structured._execute_read_only(
                f'SELECT * FROM "{table_name}"; SELECT 1',
                {table_name},
            )

    def test_answer_includes_sql_and_result_table(self):
        table_name = self.datasets[0]["table_name"]
        with patch.object(
            structured,
            "_generate_sql",
            return_value=f'SELECT SUM("revenue") AS revenue FROM "{table_name}"',
        ):
            answer = structured.answer_structured_question(
                "What is total revenue?"
            )
        self.assertIn("**Read-only SQL:**", answer)
        self.assertIn("sales.csv", answer)
        self.assertIn("| revenue |", answer)
        self.assertIn("| 350 |", answer)

    def test_user_edited_select_is_executed_without_regenerating_sql(self):
        table_name = self.datasets[0]["table_name"]
        edited_sql = f'SELECT "region" FROM "{table_name}" ORDER BY "region"'
        with patch.object(
            structured,
            "_generate_sql",
            side_effect=AssertionError("Edited SQL should not be regenerated."),
        ):
            result = structured.run_structured_query(
                "List regions", edited_sql
            )

        self.assertEqual(result["sql"], edited_sql)
        self.assertEqual(result["columns"], ["region"])
        self.assertEqual(result["rows"], [["East"], ["West"], ["West"]])
        self.assertEqual(result["sources"], ["sales.csv (Table 1)"])

    def test_sql_generation_uses_local_model_and_schema(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(
            {"message": {"content": 'SELECT SUM("revenue") FROM "sales"'}}
        ).encode()
        with patch("services.structured_data_service.urllib.request.urlopen", return_value=response) as urlopen:
            sql = structured._generate_sql(
                "What is total revenue?", self.datasets
            )

        self.assertIn("SELECT SUM", sql)
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], structured.MODEL_NAME)
        self.assertIn("revenue", payload["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
