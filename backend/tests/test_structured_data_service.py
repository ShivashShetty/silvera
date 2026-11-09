import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from services import structured_data_service as service


class ReadOnlySqlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "data.db"
        with closing(sqlite3.connect(self.database)) as connection:
            with connection:
                connection.execute(
                    'CREATE TABLE "allowed_table" ("public_col" TEXT, "secret_col" TEXT)'
                )
                connection.execute(
                    'INSERT INTO "allowed_table" VALUES ("visible", "private")'
                )
                connection.execute('CREATE TABLE "other_table" ("other_col" TEXT)')
                connection.execute('INSERT INTO "other_table" VALUES ("hidden")')
        self.database_patcher = patch.object(service, "DATABASE_PATH", self.database)
        self.database_patcher.start()
        self.columns = {"public_col"}

    def tearDown(self):
        self.database_patcher.stop()
        self.temporary.cleanup()

    def test_sql_generation_prompt_uses_exact_schema_and_repair_error(self):
        response_body = json.dumps(
            {"message": {"content": json.dumps({"sql": "SELECT public_col FROM allowed_table"})}}
        ).encode()
        with patch(
            "services.structured_data_service.urlopen",
            return_value=unittest.mock.mock_open(read_data=response_body)(),
        ) as open_url:
            statement = service.generate_sql(
                "show public values",
                "allowed_table",
                ["public_col"],
                previous_sql="SELECT missing_col FROM allowed_table",
                error="SQLite rejected the query: no such column: missing_col",
            )

        self.assertEqual(statement, "SELECT public_col FROM allowed_table")
        payload = json.loads(open_url.call_args.args[0].data)
        prompt = payload["messages"][1]["content"]
        self.assertIn('Allowed columns (JSON): ["public_col"]', prompt)
        self.assertIn("Previous SQL: SELECT missing_col FROM allowed_table", prompt)
        self.assertIn("no such column: missing_col", prompt)
        self.assertIn("COLLATE NOCASE", prompt)
        self.assertIn("never invent or assume columns", payload["messages"][0]["content"])

    def test_friendly_sql_table_name_uses_filename_and_non_default_sheet(self):
        self.assertEqual(
            service.friendly_sql_table_name(
                "Sales_Transactions_FY2025.csv",
                "Table 1",
            ),
            "Sales_Transactions_FY2025",
        )
        self.assertEqual(
            service.friendly_sql_table_name("Quarterly Sales.xlsx", "North America"),
            "Quarterly_Sales_North_America",
        )

    def test_allowed_select_and_aggregate_work(self):
        selected = service.execute_readonly_query(
            "allowed_table",
            self.columns,
            "SELECT public_col AS label FROM allowed_table",
        )
        self.assertEqual(selected["columns"], ["label"])
        self.assertEqual(selected["rows"], [["visible"]])
        aggregate = service.execute_readonly_query(
            "allowed_table",
            self.columns,
            "SELECT COUNT(*) AS row_count FROM allowed_table",
        )
        self.assertEqual(aggregate["rows"], [[1]])

    def test_readable_table_alias_preserves_column_authorization(self):
        selected = service.execute_readonly_query(
            "allowed_table",
            self.columns,
            'SELECT "public_col" FROM "Employee Directory"',
            table_alias="Employee Directory",
        )
        self.assertEqual(selected["rows"], [["visible"]])
        with self.assertRaises(service.UnsafeQueryError):
            service.execute_readonly_query(
                "allowed_table",
                self.columns,
                'SELECT secret_col FROM "Employee Directory"',
                table_alias="Employee Directory",
            )
        star = service.execute_readonly_query(
            "allowed_table",
            self.columns,
            'SELECT * FROM "Employee Directory"',
            table_alias="Employee Directory",
        )
        self.assertEqual(star["columns"], ["public_col"])
        self.assertEqual(star["rows"], [["visible"]])

    def test_nocase_text_filter_matches_csv_status_casing(self):
        with closing(sqlite3.connect(self.database)) as connection:
            with connection:
                connection.execute(
                    'UPDATE "allowed_table" SET "public_col" = "Completed"'
                )
        result = service.execute_readonly_query(
            "allowed_table",
            self.columns,
            "SELECT public_col FROM allowed_table "
            "WHERE public_col = 'completed' COLLATE NOCASE",
        )
        self.assertEqual(result["rows"], [["Completed"]])

    def test_preview_selects_only_approved_columns_and_limits_rows(self):
        preview = service.preview_dataset_rows(
            "allowed_table",
            self.columns,
            limit=1,
            offset=0,
        )
        self.assertEqual(preview["columns"], ["public_col"])
        self.assertEqual(preview["rows"], [["visible"]])

    def test_preview_rejects_out_of_range_pagination(self):
        for limit, offset in ((0, 0), (101, 0), (10, -1)):
            with self.subTest(limit=limit, offset=offset):
                with self.assertRaises(ValueError):
                    service.preview_dataset_rows(
                        "allowed_table",
                        self.columns,
                        limit=limit,
                        offset=offset,
                    )

    def test_writes_ddl_pragmas_multiple_statements_and_cte_values_are_rejected(self):
        statements = (
            "UPDATE allowed_table SET public_col='bad'",
            "DELETE FROM allowed_table",
            "DROP TABLE allowed_table",
            "PRAGMA table_info(allowed_table)",
            "SELECT public_col FROM allowed_table; SELECT 1",
            "VALUES (1)",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(service.UnsafeQueryError):
                    service.execute_readonly_query(
                        "allowed_table",
                        self.columns,
                        statement,
                    )

    def test_unapproved_table_or_column_is_rejected(self):
        for statement in (
            "SELECT secret_col FROM allowed_table",
            "SELECT other_col FROM other_table",
            "SELECT * FROM allowed_table",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(service.UnsafeQueryError):
                    service.execute_readonly_query(
                        "allowed_table",
                        self.columns,
                        statement,
                    )

    def test_sqlite_syntax_errors_include_a_fixable_diagnostic(self):
        with self.assertRaisesRegex(
            service.UnsafeQueryError,
            'SQLite rejected the query: near "FROM": syntax error',
        ):
            service.execute_readonly_query(
                "allowed_table",
                self.columns,
                "SELECT FROM allowed_table",
            )

        with self.assertRaisesRegex(
            service.UnsafeQueryError,
            "SQLite rejected the query: no such column: missing_col",
        ):
            service.execute_readonly_query(
                "allowed_table",
                self.columns,
                "SELECT missing_col FROM allowed_table",
            )

    def test_query_timeout_and_row_limit(self):
        with patch.object(service, "QUERY_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(TimeoutError):
                service.execute_readonly_query(
                    "allowed_table",
                    self.columns,
                    """
                    WITH RECURSIVE n(x) AS (
                        SELECT 1 UNION ALL SELECT x+1 FROM n
                    )
                    SELECT max(x) FROM n
                    """,
                )

        with patch.object(service, "MAX_ROWS", 1):
            with closing(sqlite3.connect(self.database)) as connection:
                with connection:
                    connection.executemany(
                        'INSERT INTO "allowed_table" VALUES (?, ?)',
                        [("second", "s"), ("third", "t")],
                    )
            result = service.execute_readonly_query(
                "allowed_table",
                self.columns,
                "SELECT public_col FROM allowed_table",
            )
            self.assertEqual(len(result["rows"]), 1)
            self.assertTrue(result["truncated"])

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
