import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from services import security


ORIGIN = "http://localhost:5173"


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        uploads = root / "uploads"
        uploads.mkdir()
        stack = ExitStack()
        stack.enter_context(patch.object(security, "DATABASE_PATH", root / "security.db"))
        stack.enter_context(patch.object(main, "UPLOAD_DIR", uploads))
        stack.enter_context(patch.object(main, "STRUCTURED_DATABASE_PATH", root / "structured.db"))
        stack.enter_context(
            patch.object(
                main.structured_data_service,
                "DATABASE_PATH",
                root / "structured.db",
            )
        )
        stack.enter_context(patch.object(main, "initialize_database", lambda: None))
        self.addCleanup(stack.close)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_authentication_csrf_and_role_protection(self):
        self.assertEqual(self.client.get("/api/documents").status_code, 401)
        self.assertTrue(self.client.get("/api/auth/setup-status").json()["setup_required"])

        setup = self.client.post(
            "/api/auth/setup",
            headers={"Origin": ORIGIN},
            json={
                "name": "First Admin",
                "username": "admin@example.test",
                "password": "Secure administrator 123",
            },
        )
        self.assertEqual(setup.status_code, 200, setup.text)
        csrf = setup.json()["csrf_token"]
        self.assertFalse(self.client.get("/api/auth/setup-status").json()["setup_required"])
        self.assertEqual(self.client.get("/api/security/overview").status_code, 200)

        denied_csrf = self.client.post(
            "/api/security/users",
            headers={"Origin": ORIGIN},
            json={
                "name": "Employee",
                "username": "employee@example.test",
                "password": "Employee password 123",
                "role": "EMPLOYEE",
            },
        )
        self.assertEqual(denied_csrf.status_code, 403)

        created = self.client.post(
            "/api/security/users",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={
                "name": "Employee",
                "username": "employee@example.test",
                "password": "Employee password 123",
                "role": "EMPLOYEE",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)

        with TestClient(main.app) as employee_client:
            login = employee_client.post(
                "/api/auth/login",
                headers={"Origin": ORIGIN},
                json={
                    "username": "employee@example.test",
                    "password": "Employee password 123",
                },
            )
            self.assertEqual(login.status_code, 200, login.text)
            self.assertEqual(employee_client.get("/api/security/overview").status_code, 403)
            upload = employee_client.post(
                "/api/documents/upload",
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": login.json()["csrf_token"],
                },
                files={"file": ("sample.pdf", b"%PDF-1.4", "application/pdf")},
            )
            self.assertEqual(upload.status_code, 403)

        logout = self.client.post(
            "/api/auth/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/security/overview").status_code, 401)

    def test_dataset_schema_and_execution_follow_column_grants(self):
        structured_path = main.STRUCTURED_DATABASE_PATH
        columns = json.dumps(
            [
                {"name": "Public", "sql_name": "public_col"},
                {"name": "Secret", "sql_name": "secret_col"},
            ]
        )
        with closing(sqlite3.connect(structured_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE structured_tables(
                        table_name TEXT, document_id TEXT, filename TEXT,
                        sheet_name TEXT, columns_json TEXT, row_count INTEGER
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO structured_tables VALUES (?, ?, ?, ?, ?, ?)",
                    ("permitted_table", "doc1", "data.csv", "Sheet1", columns, 1),
                )
                connection.execute(
                    'CREATE TABLE "permitted_table" ("public_col" TEXT, "secret_col" TEXT)'
                )
                connection.execute(
                    'INSERT INTO "permitted_table" VALUES ("visible", "restricted")'
                )

        setup = self.client.post(
            "/api/auth/setup",
            headers={"Origin": ORIGIN},
            json={
                "name": "First Admin",
                "username": "admin@example.test",
                "password": "Secure administrator 123",
            },
        )
        self.assertEqual(setup.status_code, 200, setup.text)
        csrf = setup.json()["csrf_token"]
        created = self.client.post(
            "/api/security/users",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={
                "name": "Employee",
                "username": "employee@example.test",
                "password": "Employee password 123",
                "role": "EMPLOYEE",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        employee = created.json()["user"]

        with TestClient(main.app) as employee_client:
            login = employee_client.post(
                "/api/auth/login",
                headers={"Origin": ORIGIN},
                json={
                    "username": "employee@example.test",
                    "password": "Employee password 123",
                },
            )
            self.assertEqual(login.status_code, 200, login.text)
            employee_csrf = login.json()["csrf_token"]
            self.assertEqual(employee_client.get("/api/datasets").json()["datasets"], [])
            denied = employee_client.post(
                "/api/data/ask",
                headers={"Origin": ORIGIN, "X-CSRF-Token": employee_csrf},
                json={
                    "question": "show rows",
                    "dataset_id": "permitted_table",
                    "sql": "SELECT public_col FROM permitted_table",
                },
            )
            self.assertEqual(denied.status_code, 404)
            denied_preview = employee_client.get(
                "/api/datasets/permitted_table/preview"
            )
            self.assertEqual(denied_preview.status_code, 404)

            grant = self.client.put(
                "/api/security/datasets/permitted_table/grants",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={
                    "principal_type": "user",
                    "principal_id": employee["id"],
                    "permissions": ["query"],
                    "columns": ["public_col"],
                },
            )
            self.assertEqual(grant.status_code, 200, grant.text)
            visible_datasets = employee_client.get("/api/datasets").json()["datasets"]
            self.assertEqual(visible_datasets[0]["columns"], ["public_col"])
            self.assertEqual(visible_datasets[0]["table_name"], "data")
            preview = employee_client.get(
                "/api/datasets/permitted_table/preview?offset=0&limit=10"
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["columns"], ["public_col"])
            self.assertEqual(preview.json()["rows"], [["visible"]])
            self.assertEqual(preview.json()["row_count"], 1)
            self.assertEqual(
                employee_client.get(
                    "/api/datasets/permitted_table/preview?offset=-1"
                ).status_code,
                422,
            )

            allowed = employee_client.post(
                "/api/data/ask",
                headers={"Origin": ORIGIN, "X-CSRF-Token": employee_csrf},
                json={
                    "question": "show rows",
                    "dataset_id": "permitted_table",
                    "sql": "SELECT public_col FROM permitted_table",
                },
            )
            self.assertEqual(allowed.status_code, 200, allowed.text)
            self.assertEqual(allowed.json()["rows"], [["visible"]])
            generated_sql = 'SELECT missing_col FROM "data"'
            with patch.object(
                main.structured_data_service,
                "generate_sql",
                return_value=generated_sql,
            ):
                failed_generated_query = self.client.post(
                    "/api/data/ask",
                    headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                    json={
                        "question": "show rows",
                        "dataset_id": "permitted_table",
                    },
                )
            self.assertEqual(failed_generated_query.status_code, 400)
            self.assertEqual(
                failed_generated_query.json()["detail"],
                {
                    "message": "SQLite rejected the query: no such column: missing_col",
                    "sql": generated_sql,
                },
            )
            with patch.object(
                main.structured_data_service,
                "generate_sql",
                side_effect=[
                    'SELECT sales FROM "data"',
                    'SELECT public_col FROM "data"',
                ],
            ) as generate_sql:
                repaired_query = self.client.post(
                    "/api/data/ask",
                    headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                    json={
                        "question": "show rows",
                        "dataset_id": "permitted_table",
                    },
                )
            self.assertEqual(repaired_query.status_code, 200, repaired_query.text)
            self.assertEqual(
                repaired_query.json()["sql"],
                'SELECT public_col FROM "data"',
            )
            self.assertEqual(repaired_query.json()["rows"], [["visible"]])
            self.assertEqual(generate_sql.call_count, 2)
            self.assertEqual(generate_sql.call_args_list[0].args[1], "data")
            self.assertEqual(
                generate_sql.call_args.kwargs,
                {
                    "previous_sql": 'SELECT sales FROM "data"',
                    "error": (
                        "SQLite rejected the query: no such column: sales"
                    ),
                },
            )
            restricted = employee_client.post(
                "/api/data/ask",
                headers={"Origin": ORIGIN, "X-CSRF-Token": employee_csrf},
                json={
                    "question": "show secrets",
                    "dataset_id": "permitted_table",
                    "sql": "SELECT secret_col FROM permitted_table",
                },
            )
            self.assertEqual(restricted.status_code, 400)
            self.assertNotIn("secret_col", restricted.text)

    def test_supported_documents_upload_and_citation_text_are_accessible(self):
        setup = self.client.post(
            "/api/auth/setup",
            headers={"Origin": ORIGIN},
            json={
                "name": "First Admin",
                "username": "admin@example.test",
                "password": "Secure administrator 123",
            },
        )
        self.assertEqual(setup.status_code, 200, setup.text)

        with patch.object(main, "index_document_pages", return_value=1):
            uploaded = self.client.post(
                "/api/documents/upload",
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": setup.json()["csrf_token"],
                },
                files={
                    "file": (
                        "policy.md",
                        b"# Quarterly policy\nKeep records for seven years.",
                        "text/markdown",
                    )
                },
            )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["index_status"], "processing")
        document_id = uploaded.json()["document_id"]

        page = self.client.get(f"/api/documents/{document_id}/pages/1")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("Keep records for seven years.", page.json()["text"])

        original = self.client.get(f"/api/documents/{document_id}/download")
        self.assertEqual(original.status_code, 200, original.text)
        self.assertIn("attachment", original.headers["content-disposition"])
        self.assertEqual(
            original.content,
            b"# Quarterly policy\nKeep records for seven years.",
        )
        listed = self.client.get("/api/documents").json()["documents"]
        self.assertEqual(listed[0]["filename"], "policy.md")
        self.assertEqual(listed[0]["index_status"], "ready")
        self.assertEqual(listed[0]["index_progress"], 100)

    def test_document_indexing_failure_is_reported_in_document_status(self):
        setup = self.client.post(
            "/api/auth/setup",
            headers={"Origin": ORIGIN},
            json={
                "name": "First Admin",
                "username": "admin@example.test",
                "password": "Secure administrator 123",
            },
        )
        self.assertEqual(setup.status_code, 200, setup.text)

        with patch.object(
            main,
            "index_document_pages",
            side_effect=RuntimeError("embedding service unavailable"),
        ):
            uploaded = self.client.post(
                "/api/documents/upload",
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": setup.json()["csrf_token"],
                },
                files={
                    "file": (
                        "policy.txt",
                        b"Keep records for seven years.",
                        "text/plain",
                    )
                },
            )

        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        listed = self.client.get("/api/documents").json()["documents"]
        self.assertEqual(listed[0]["index_status"], "failed")
        self.assertEqual(listed[0]["index_progress"], 0)
        self.assertIn("search index", listed[0]["index_error"])

    def test_upload_size_limit_is_reported_and_enforced(self):
        self.assertEqual(
            self.client.get("/api/status").json()["max_upload_mb"],
            main.MAX_UPLOAD_MB,
        )
        setup = self.client.post(
            "/api/auth/setup",
            headers={"Origin": ORIGIN},
            json={
                "name": "First Admin",
                "username": "admin@example.test",
                "password": "Secure administrator 123",
            },
        )
        self.assertEqual(setup.status_code, 200, setup.text)

        with patch.object(main, "MAX_FILE_SIZE", 4):
            rejected = self.client.post(
                "/api/documents/upload",
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": setup.json()["csrf_token"],
                },
                files={"file": ("notes.txt", b"12345", "text/plain")},
            )
        self.assertEqual(rejected.status_code, 413)

if __name__ == "__main__":
    unittest.main()
