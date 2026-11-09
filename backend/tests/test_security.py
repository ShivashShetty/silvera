import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from services import security


class SecurityServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir()
        self.chat_db = self.root / "chat_history.db"
        self.structured_db = self.root / "structured_data.db"
        self.database_patcher = patch.object(
            security,
            "DATABASE_PATH",
            self.root / "security.db",
        )
        self.database_patcher.start()
        security.initialize_database()

    def tearDown(self):
        self.database_patcher.stop()
        self.temporary.cleanup()

    def create_admin(self):
        return security.create_initial_admin(
            "Admin",
            "admin@example.test",
            "Correct horse battery staple",
            upload_dir=self.uploads,
            structured_db_path=self.structured_db,
            conversation_db_path=self.chat_db,
        )

    def test_initial_setup_imports_existing_resources_as_private(self):
        document_id = "doc-legacy"
        (self.uploads / f"{document_id}.txt").write_text("private", encoding="utf-8")
        (self.uploads / f"{document_id}.meta").write_text(
            json.dumps({"filename": "private.pdf", "uploaded_at": "2025-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )
        with closing(sqlite3.connect(self.structured_db)) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE structured_tables(table_name TEXT, columns_json TEXT, document_id TEXT)"
                )
                connection.execute(
                    "INSERT INTO structured_tables VALUES (?, ?, ?)",
                    ("legacy_table", json.dumps([{"sql_name": "secret"}]), "legacy"),
                )
        with closing(sqlite3.connect(self.chat_db)) as connection:
            with connection:
                connection.execute("CREATE TABLE conversations(id TEXT)")
                connection.execute("INSERT INTO conversations VALUES ('legacy-chat')")

        admin = self.create_admin()
        employee = security.create_user(
            admin,
            "Employee",
            "employee@example.test",
            "Employee password 12",
            "EMPLOYEE",
        )
        self.assertEqual(
            security.document_ids_for(employee, "view"),
            [],
        )
        self.assertEqual(
            security.dataset_access(employee, "legacy_table"),
            None,
        )
        self.assertTrue(security.accessible_conversation(admin, "legacy-chat"))
        self.assertFalse(security.accessible_conversation(employee, "legacy-chat"))
        with security.get_connection() as connection:
            document = connection.execute(
                "SELECT owner_id, visibility, classification FROM documents WHERE id=?",
                (document_id,),
            ).fetchone()
            dataset = connection.execute(
                "SELECT owner_id, visibility, classification FROM datasets WHERE id=?",
                ("legacy_table",),
            ).fetchone()
        self.assertEqual(tuple(document), (admin["id"], "private", "restricted"))
        self.assertEqual(tuple(dataset), (admin["id"], "private", "restricted"))

    def test_document_grants_are_enforced_by_permission(self):
        admin = self.create_admin()
        first = security.create_user(
            admin, "First", "first@example.test", "First password 12", "EMPLOYEE"
        )
        second = security.create_user(
            admin, "Second", "second@example.test", "Second password 12", "VIEWER"
        )
        security.register_document("doc-1", admin["id"], security.timestamp())
        security.set_document_grant(
            admin,
            "doc-1",
            "user",
            first["id"],
            ["view", "query"],
        )
        self.assertTrue(security.can_access_document(first, "doc-1", "view"))
        self.assertTrue(security.can_access_document(first, "doc-1", "query"))
        self.assertFalse(security.can_access_document(first, "doc-1", "delete"))
        self.assertFalse(security.can_access_document(second, "doc-1", "view"))

    def test_dataset_grant_limits_columns(self):
        admin = self.create_admin()
        employee = security.create_user(
            admin, "Employee", "employee@example.test", "Employee password 12", "EMPLOYEE"
        )
        with security.get_connection() as connection:
            connection.execute(
                """
                INSERT INTO datasets(id, table_name, owner_id, columns_json)
                VALUES ('table1', 'table1', ?, ?)
                """,
                (admin["id"], json.dumps(["public_col", "secret_col"])),
            )
        security.set_dataset_grant(
            admin,
            "table1",
            "user",
            employee["id"],
            ["query"],
            ["public_col"],
        )
        policy, columns = security.dataset_access(employee, "table1")
        self.assertEqual(policy["table_name"], "table1")
        self.assertEqual(columns, {"public_col"})

    def test_login_lockout_sessions_and_disabled_users(self):
        admin = self.create_admin()
        user, error = security.login(
            "ADMIN@example.test",
            "Correct horse battery staple",
            "127.0.0.1",
        )
        self.assertEqual(error, "")
        self.assertEqual(user["id"], admin["id"])
        token, csrf_token, _ = security.create_session(admin["id"])
        self.assertEqual(security.user_from_session(token)["id"], admin["id"])
        self.assertTrue(security.verify_csrf(token, csrf_token))
        self.assertFalse(security.verify_csrf(token, "bad-token"))

        for _ in range(5):
            user, _ = security.login("admin@example.test", "wrong password", "192.0.2.1")
            self.assertIsNone(user)
        user, error = security.login(
            "admin@example.test",
            "Correct horse battery staple",
            "192.0.2.1",
        )
        self.assertIsNone(user)
        self.assertIn("temporarily", error)

        with security.get_connection() as connection:
            connection.execute(
                "UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?",
                (security._token_digest(token),),
            )
        self.assertIsNone(security.user_from_session(token))

    def test_last_active_admin_cannot_be_disabled_or_demoted(self):
        admin = self.create_admin()
        with self.assertRaises(ValueError):
            security.update_user(admin, admin["id"], active=False)
        with self.assertRaises(ValueError):
            security.update_user(admin, admin["id"], role="MANAGER")

    def test_audit_records_cannot_be_updated_or_deleted(self):
        self.create_admin()
        security.audit("test_event")
        with self.assertRaises(sqlite3.IntegrityError):
            with security.get_connection() as connection:
                connection.execute(
                    "UPDATE audit_events SET result='changed' WHERE event_type='test_event'"
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with security.get_connection() as connection:
                connection.execute("DELETE FROM audit_events WHERE event_type='test_event'")

    def test_retention_preview_does_not_remove_data(self):
        admin = self.create_admin()
        security.register_document(
            "old-doc",
            admin["id"],
            "2020-01-01T00:00:00+00:00",
        )
        security.set_retention_days(admin, 1)
        preview = security.retention_preview()
        self.assertEqual(preview["count"], 1)
        self.assertEqual(preview["affected_documents"][0]["document_id"], "old-doc")
        with security.get_connection() as connection:
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM documents WHERE id='old-doc'"
                ).fetchone()
            )


if __name__ == "__main__":
    unittest.main()
