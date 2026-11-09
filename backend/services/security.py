import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import bcrypt
from contextvars import ContextVar


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = Path(
    os.environ.get("SILVERA_SECURITY_DB", str(DATA_DIR / "security.db"))
)
SESSION_TTL_HOURS = max(
    1,
    min(int(os.environ.get("SILVERA_SESSION_TTL_HOURS", "12")), 24 * 30),
)
COOKIE_SECURE = os.environ.get("SILVERA_COOKIE_SECURE", "false").lower() in {
    "1",
    "true",
    "yes",
}
ROLES = ("ADMIN", "MANAGER", "EMPLOYEE", "VIEWER")
DOCUMENT_PERMISSIONS = ("view", "query", "download", "manage", "delete")
DATASET_PERMISSIONS = ("query", "manage")
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
VISIBILITIES = ("private", "shared", "organization")
_REQUEST_ID: ContextVar[str | None] = ContextVar("silvera_request_id", default=None)


def set_request_id(request_id: str) -> None:
    _REQUEST_ID.set(request_id)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=10,
        factory=ClosingConnection,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash BLOB NOT NULL,
                role TEXT NOT NULL CHECK (role IN
                    ('ADMIN', 'MANAGER', 'EMPLOYEE', 'VIEWER')),
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS login_attempts (
                username_key TEXT NOT NULL,
                client_key TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                locked_until TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (username_key, client_key)
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES users(id),
                visibility TEXT NOT NULL DEFAULT 'private'
                    CHECK (visibility IN ('private', 'shared', 'organization')),
                classification TEXT NOT NULL DEFAULT 'restricted'
                    CHECK (classification IN
                        ('public', 'internal', 'confidential', 'restricted')),
                uploaded_at TEXT,
                archived_at TEXT
            );
            CREATE TABLE IF NOT EXISTS document_grants (
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                principal_type TEXT NOT NULL CHECK
                    (principal_type IN ('user', 'role')),
                principal_id TEXT NOT NULL,
                permissions_json TEXT NOT NULL,
                PRIMARY KEY (document_id, principal_type, principal_id)
            );
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                table_name TEXT NOT NULL UNIQUE,
                owner_id TEXT NOT NULL REFERENCES users(id),
                visibility TEXT NOT NULL DEFAULT 'private'
                    CHECK (visibility IN ('private', 'shared', 'organization')),
                classification TEXT NOT NULL DEFAULT 'restricted'
                    CHECK (classification IN
                        ('public', 'internal', 'confidential', 'restricted')),
                columns_json TEXT NOT NULL DEFAULT '[]',
                archived_at TEXT
            );
            CREATE TABLE IF NOT EXISTS dataset_grants (
                dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                principal_type TEXT NOT NULL CHECK
                    (principal_type IN ('user', 'role')),
                principal_id TEXT NOT NULL,
                permissions_json TEXT NOT NULL,
                columns_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (dataset_id, principal_type, principal_id)
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                actor_id TEXT,
                event_type TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                result TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                request_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_actor
                ON audit_events(actor_id, timestamp DESC);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS audit_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only');
            END;
            """
        )


def audit(
    event_type: str,
    *,
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    result: str = "success",
    metadata: dict | None = None,
    request_id: str | None = None,
) -> None:
    request_id = request_id or _REQUEST_ID.get()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO audit_events (
                id, timestamp, actor_id, event_type, resource_type,
                resource_id, result, metadata_json, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                timestamp(),
                actor_id,
                event_type[:100],
                resource_type[:100] if resource_type else None,
                resource_id[:200] if resource_id else None,
                result[:30],
                json.dumps(metadata or {}, ensure_ascii=True)[:4000],
                request_id,
            ),
        )


def is_setup_required() -> bool:
    with get_connection() as connection:
        return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def _import_legacy_resources(
    connection: sqlite3.Connection,
    admin_id: str,
    upload_dir: Path,
    structured_db_path: Path,
    conversation_db_path: Path,
) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
        ("legacy_import_complete", "0", timestamp()),
    )
    if upload_dir.is_dir():
        for text_path in upload_dir.glob("*.txt"):
            document_id = text_path.stem
            try:
                metadata = json.loads(
                    (upload_dir / f"{document_id}.meta").read_text(
                        encoding="utf-8"
                    )
                )
                uploaded_at = metadata.get("uploaded_at")
            except (OSError, json.JSONDecodeError):
                uploaded_at = None
            connection.execute(
                """
                INSERT OR IGNORE INTO documents
                    (id, owner_id, visibility, classification, uploaded_at)
                VALUES (?, ?, 'private', 'restricted', ?)
                """,
                (document_id, admin_id, uploaded_at),
            )

    if structured_db_path.is_file():
        source = sqlite3.connect(
            f"file:{structured_db_path.resolve().as_posix()}?mode=ro",
            uri=True,
        )
        try:
            has_registry = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                ("structured_tables",),
            ).fetchone()
            if has_registry:
                for table_name, columns_json in source.execute(
                    "SELECT table_name, columns_json FROM structured_tables"
                ):
                    try:
                        raw_columns = json.loads(columns_json)
                        columns = [
                            item.get("sql_name", item.get("name", ""))
                            if isinstance(item, dict)
                            else item
                            for item in raw_columns
                        ]
                        columns = [column for column in columns if isinstance(column, str) and column]
                    except (TypeError, json.JSONDecodeError):
                        columns = []
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO datasets
                            (id, table_name, owner_id, visibility,
                             classification, columns_json)
                        VALUES (?, ?, ?, 'private', 'restricted', ?)
                        """,
                        (
                            table_name,
                            table_name,
                            admin_id,
                            json.dumps(columns, ensure_ascii=True),
                        ),
                    )
        finally:
            source.close()

    if conversation_db_path.is_file():
        source = sqlite3.connect(
            f"file:{conversation_db_path.resolve().as_posix()}?mode=ro",
            uri=True,
        )
        try:
            for (conversation_id,) in source.execute(
                "SELECT id FROM conversations"
            ):
                connection.execute(
                    "INSERT OR IGNORE INTO conversations(id, owner_id) VALUES (?, ?)",
                    (conversation_id, admin_id),
                )
        finally:
            source.close()

    connection.execute(
        "UPDATE settings SET value='1', updated_at=? WHERE key=?",
        (timestamp(), "legacy_import_complete"),
    )


def create_initial_admin(
    name: str,
    username: str,
    password: str,
    *,
    upload_dir: Path,
    structured_db_path: Path,
    conversation_db_path: Path,
) -> dict:
    name = name.strip()
    username = username.strip().lower()
    if len(name) < 1 or len(name) > 100:
        raise ValueError("Name must contain 1 to 100 characters.")
    if len(username) < 3 or len(username) > 254 or "@" not in username:
        raise ValueError("Enter a valid email address as the username.")
    validate_password(password)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
    admin_id = str(uuid4())
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise RuntimeError("Initial administrator setup is already complete.")
        connection.execute(
            """
            INSERT INTO users(id, name, username, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, 'ADMIN', ?)
            """,
            (admin_id, name, username, password_hash, timestamp()),
        )
        _import_legacy_resources(
            connection,
            admin_id,
            upload_dir,
            structured_db_path,
            conversation_db_path,
        )
    audit(
        "initial_admin_created",
        actor_id=admin_id,
        resource_type="user",
        resource_id=admin_id,
        metadata={"legacy_resources_private": True},
    )
    return get_user(admin_id)


def validate_password(password: str) -> None:
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise ValueError("Password must be at least 12 characters and no more than 72 UTF-8 bytes.")


def create_user(
    actor: dict,
    name: str,
    username: str,
    password: str,
    role: str,
) -> dict:
    name = name.strip()
    username = username.strip().lower()
    role = role.upper()
    if actor["role"] != "ADMIN":
        raise PermissionError("Administrator access is required.")
    if role not in ROLES:
        raise ValueError("Invalid role.")
    if len(name) < 1 or len(name) > 100:
        raise ValueError("Name must contain 1 to 100 characters.")
    if len(username) < 3 or len(username) > 254 or "@" not in username:
        raise ValueError("Enter a valid email address as the username.")
    validate_password(password)
    user_id = str(uuid4())
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO users(id, name, username, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, name, username, password_hash, role, timestamp()),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("A user with that email already exists.") from exc
    audit(
        "user_created",
        actor_id=actor["id"],
        resource_type="user",
        resource_id=user_id,
        metadata={"role": role},
    )
    return get_user(user_id)


def get_user(user_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, name, username, role, active, created_at, last_login_at
            FROM users WHERE id=?
            """,
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def list_users(search: str = "") -> list[dict]:
    term = f"%{search.strip()}%"
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, name, username, role, active, created_at, last_login_at
            FROM users
            WHERE name LIKE ? OR username LIKE ?
            ORDER BY name COLLATE NOCASE
            LIMIT 500
            """,
            (term, term),
        ).fetchall()
    return [dict(row) for row in rows]


def update_user(
    actor: dict,
    user_id: str,
    *,
    name: str | None = None,
    role: str | None = None,
    active: bool | None = None,
) -> dict:
    if actor["role"] != "ADMIN":
        raise PermissionError("Administrator access is required.")
    current = get_user(user_id)
    if current is None:
        raise LookupError("User not found.")
    new_role = role.upper() if role is not None else current["role"]
    if new_role not in ROLES:
        raise ValueError("Invalid role.")
    new_name = name.strip() if name is not None else current["name"]
    if not new_name or len(new_name) > 100:
        raise ValueError("Name must contain 1 to 100 characters.")
    new_active = bool(active) if active is not None else bool(current["active"])
    with get_connection() as connection:
        if current["role"] == "ADMIN" and (
            new_role != "ADMIN" or not new_active
        ):
            active_admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role='ADMIN' AND active=1"
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError("Cannot remove or disable the only active administrator.")
        connection.execute(
            "UPDATE users SET name=?, role=?, active=? WHERE id=?",
            (new_name, new_role, int(new_active), user_id),
        )
        if not new_active:
            connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    audit(
        "user_modified",
        actor_id=actor["id"],
        resource_type="user",
        resource_id=user_id,
        metadata={"role": new_role, "active": new_active},
    )
    return get_user(user_id)


def reset_password(actor: dict, user_id: str, password: str) -> None:
    if actor["role"] != "ADMIN":
        raise PermissionError("Administrator access is required.")
    validate_password(password)
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (password_hash, user_id),
        )
        if cursor.rowcount == 0:
            raise LookupError("User not found.")
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    audit(
        "password_reset",
        actor_id=actor["id"],
        resource_type="user",
        resource_id=user_id,
    )


def change_password(
    user_id: str,
    current_password: str,
    new_password: str,
    current_session_token: str,
) -> None:
    validate_password(new_password)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT password_hash FROM users WHERE id=? AND active=1",
            (user_id,),
        ).fetchone()
        try:
            valid = row is not None and bcrypt.checkpw(
                current_password.encode("utf-8"),
                row["password_hash"],
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise PermissionError("Current password is incorrect.")
        password_hash = bcrypt.hashpw(
            new_password.encode("utf-8"),
            bcrypt.gensalt(rounds=12),
        )
        current_hash = _token_digest(current_session_token)
        connection.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (password_hash, user_id),
        )
        connection.execute(
            "DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
            (user_id, current_hash),
        )
    audit(
        "password_changed",
        actor_id=user_id,
        resource_type="user",
        resource_id=user_id,
    )


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(user_id: str) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    created = utc_now()
    expires = created + timedelta(hours=SESSION_TTL_HOURS)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO sessions(token_hash, user_id, csrf_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                _token_digest(token),
                user_id,
                _token_digest(csrf_token),
                timestamp(created),
                timestamp(expires),
            ),
        )
    return token, csrf_token, timestamp(expires)


def user_from_session(token: str | None) -> dict | None:
    if not token:
        return None
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT u.id, u.name, u.username, u.role, u.active,
                   u.created_at, u.last_login_at, s.expires_at
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=?
            """,
            (_token_digest(token),),
        ).fetchone()
        if row is None:
            return None
        if row["active"] != 1 or row["expires_at"] <= timestamp():
            connection.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (_token_digest(token),),
            )
            return None
    return dict(row)


def verify_csrf(session_token: str, csrf_token: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT csrf_hash FROM sessions WHERE token_hash=?",
            (_token_digest(session_token),),
        ).fetchone()
    return bool(
        row
        and hmac.compare_digest(row["csrf_hash"], _token_digest(csrf_token))
    )


def logout(session_token: str | None, user_id: str | None) -> None:
    if session_token:
        with get_connection() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (_token_digest(session_token),),
            )
    audit("logout", actor_id=user_id)


def login(
    username: str,
    password: str,
    client_key: str,
) -> tuple[dict | None, str]:
    normalized = username.strip().lower()[:254]
    client_key = client_key[:100]
    now = utc_now()
    with get_connection() as connection:
        attempt = connection.execute(
            """
            SELECT attempts, locked_until FROM login_attempts
            WHERE username_key=? AND client_key=?
            """,
            (normalized, client_key),
        ).fetchone()
        if attempt and attempt["locked_until"]:
            try:
                locked_until = datetime.fromisoformat(attempt["locked_until"])
            except ValueError:
                locked_until = now
            if locked_until > now:
                connection.commit()
                audit(
                    "login_failed",
                    result="rate_limited",
                    metadata={"username": normalized},
                )
                return None, "Login temporarily unavailable. Try again later."
        row = connection.execute(
            """
            SELECT id, name, username, password_hash, role, active,
                   created_at, last_login_at
            FROM users WHERE username=?
            """,
            (normalized,),
        ).fetchone()
        valid = False
        if row is not None:
            try:
                valid = bcrypt.checkpw(password.encode(), row["password_hash"])
            except (ValueError, TypeError):
                valid = False
        if row is None or not valid or row["active"] != 1:
            count = (attempt["attempts"] if attempt else 0) + 1
            locked_until = (
                timestamp(now + timedelta(minutes=15))
                if count >= 5
                else None
            )
            connection.execute(
                """
                INSERT INTO login_attempts
                    (username_key, client_key, attempts, locked_until, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(username_key, client_key) DO UPDATE SET
                    attempts=excluded.attempts,
                    locked_until=excluded.locked_until,
                    updated_at=excluded.updated_at
                """,
                (normalized, client_key, count, locked_until, timestamp(now)),
            )
            connection.commit()
            audit(
                "login_failed",
                actor_id=row["id"] if row else None,
                result="denied",
                metadata={"username": normalized, "reason": "invalid_credentials"},
            )
            return None, "Invalid username or password."

        connection.execute(
            "DELETE FROM login_attempts WHERE username_key=? AND client_key=?",
            (normalized, client_key),
        )
        connection.execute(
            "UPDATE users SET last_login_at=? WHERE id=?",
            (timestamp(now), row["id"]),
        )
        user = dict(row)
        user.pop("password_hash", None)
    audit("login_succeeded", actor_id=user["id"], resource_type="user", resource_id=user["id"])
    return user, ""


def _permissions_for(
    connection: sqlite3.Connection,
    table: str,
    grants_table: str,
    resource_column: str,
    resource_id: str,
    user: dict,
    permission: str,
) -> bool:
    row = connection.execute(
        f"SELECT owner_id, visibility, archived_at FROM {table} WHERE id=?",
        (resource_id,),
    ).fetchone()
    if row is None or row["archived_at"] is not None:
        return False
    if user["role"] == "ADMIN" or row["owner_id"] == user["id"]:
        return True
    if row["visibility"] == "organization":
        return permission in ("view", "query", "download")
    grants = connection.execute(
        f"""
        SELECT permissions_json FROM {grants_table}
        WHERE {resource_column}=? AND (
            (principal_type='user' AND principal_id=?) OR
            (principal_type='role' AND principal_id=?)
        )
        """,
        (resource_id, user["id"], user["role"]),
    ).fetchall()
    for grant in grants:
        try:
            if permission in json.loads(grant["permissions_json"]):
                return True
        except (TypeError, json.JSONDecodeError):
            continue
    return False


def document_ids_for(user: dict, permission: str) -> list[str]:
    if permission not in DOCUMENT_PERMISSIONS:
        raise ValueError("Invalid document permission.")
    with get_connection() as connection:
        ids = connection.execute("SELECT id FROM documents").fetchall()
        return [
            row["id"]
            for row in ids
            if _permissions_for(
                connection,
                "documents",
                "document_grants",
                "document_id",
                row["id"],
                user,
                permission,
            )
        ]


def can_access_document(user: dict, document_id: str, permission: str) -> bool:
    if permission not in DOCUMENT_PERMISSIONS:
        return False
    if user.get("role") == "VIEWER" and permission in {"manage", "delete"}:
        return False
    with get_connection() as connection:
        return _permissions_for(
            connection,
            "documents",
            "document_grants",
            "document_id",
            document_id,
            user,
            permission,
        )


def register_document(document_id: str, owner_id: str, uploaded_at: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO documents(id, owner_id, uploaded_at, visibility, classification)
            VALUES (?, ?, ?, 'private', 'internal')
            """,
            (document_id, owner_id, uploaded_at),
        )


def list_accessible_documents(user: dict, permission: str = "view") -> list[dict]:
    allowed = set(document_ids_for(user, permission))
    if not allowed:
        return []
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM documents WHERE archived_at IS NULL"
        ).fetchall()
    return [dict(row) for row in rows if row["id"] in allowed]


def security_documents(user: dict) -> list[dict]:
    with get_connection() as connection:
        if user["role"] == "ADMIN":
            rows = connection.execute(
                "SELECT * FROM documents ORDER BY uploaded_at DESC"
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM documents
                WHERE owner_id=? ORDER BY uploaded_at DESC
                """,
                (user["id"],),
            ).fetchall()
    return [dict(row) for row in rows]


def document_grants(document_id: str) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT principal_type, principal_id, permissions_json
            FROM document_grants WHERE document_id=?
            ORDER BY principal_type, principal_id
            """,
            (document_id,),
        ).fetchall()
    return [
        {
            "principal_type": row["principal_type"],
            "principal_id": row["principal_id"],
            "permissions": json.loads(row["permissions_json"]),
        }
        for row in rows
    ]


def set_document_policy(
    actor: dict,
    document_id: str,
    *,
    visibility: str | None = None,
    classification: str | None = None,
) -> dict:
    if visibility is not None and visibility not in VISIBILITIES:
        raise ValueError("Invalid document visibility.")
    if classification is not None and classification not in CLASSIFICATIONS:
        raise ValueError("Invalid document classification.")
    if not (
        actor["role"] == "ADMIN"
        or (
            actor["role"] == "MANAGER"
            and can_access_document(actor, document_id, "manage")
        )
    ):
        raise PermissionError("You cannot manage this document.")
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE documents
            SET visibility=COALESCE(?, visibility),
                classification=COALESCE(?, classification)
            WHERE id=? AND archived_at IS NULL
            """,
            (visibility, classification, document_id),
        )
        if cursor.rowcount == 0:
            raise LookupError("Document not found.")
    audit(
        "document_policy_changed",
        actor_id=actor["id"],
        resource_type="document",
        resource_id=document_id,
        metadata={"visibility": visibility, "classification": classification},
    )
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE id=?", (document_id,)
        ).fetchone()
    return dict(row)


def set_document_grant(
    actor: dict,
    document_id: str,
    principal_type: str,
    principal_id: str,
    permissions: list[str],
) -> None:
    if not (
        actor["role"] == "ADMIN"
        or (
            actor["role"] == "MANAGER"
            and can_access_document(actor, document_id, "manage")
        )
    ):
        raise PermissionError("You cannot manage this document.")
    if principal_type not in ("user", "role"):
        raise ValueError("Grant principal must be a user or role.")
    if principal_type == "role" and principal_id not in ROLES:
        raise ValueError("Invalid role.")
    if (
        actor["role"] == "MANAGER"
        and principal_type == "role"
        and principal_id == "ADMIN"
    ):
        raise PermissionError("Managers cannot grant administrator access.")
    if any(permission not in DOCUMENT_PERMISSIONS for permission in permissions):
        raise ValueError("Invalid document permission.")
    with get_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM documents WHERE id=?", (document_id,)
        ).fetchone() is None:
            raise LookupError("Document not found.")
        if principal_type == "user" and connection.execute(
            "SELECT 1 FROM users WHERE id=? AND active=1", (principal_id,)
        ).fetchone() is None:
            raise ValueError("Active user not found.")
        connection.execute(
            """
            INSERT INTO document_grants
                (document_id, principal_type, principal_id, permissions_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(document_id, principal_type, principal_id)
            DO UPDATE SET permissions_json=excluded.permissions_json
            """,
            (document_id, principal_type, principal_id, json.dumps(sorted(set(permissions)))),
        )
    audit(
        "document_permission_changed",
        actor_id=actor["id"],
        resource_type="document",
        resource_id=document_id,
        metadata={"principal_type": principal_type, "principal_id": principal_id, "permissions": permissions},
    )


def dataset_ids_for(user: dict, permission: str = "query") -> list[str]:
    if permission not in DATASET_PERMISSIONS:
        raise ValueError("Invalid dataset permission.")
    with get_connection() as connection:
        rows = connection.execute("SELECT id FROM datasets").fetchall()
        return [
            row["id"]
            for row in rows
            if _permissions_for(
                connection,
                "datasets",
                "dataset_grants",
                "dataset_id",
                row["id"],
                user,
                permission,
            )
        ]


def dataset_policy(dataset_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM datasets WHERE id=?", (dataset_id,)
        ).fetchone()
    return dict(row) if row else None


def set_dataset_policy(
    actor: dict,
    dataset_id: str,
    *,
    visibility: str | None = None,
    classification: str | None = None,
) -> dict:
    if actor["role"] != "ADMIN":
        raise PermissionError("Administrator access is required.")
    if visibility is not None and visibility not in VISIBILITIES:
        raise ValueError("Invalid dataset visibility.")
    if classification is not None and classification not in CLASSIFICATIONS:
        raise ValueError("Invalid dataset classification.")
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE datasets
            SET visibility=COALESCE(?, visibility),
                classification=COALESCE(?, classification)
            WHERE id=? AND archived_at IS NULL
            """,
            (visibility, classification, dataset_id),
        )
        if cursor.rowcount == 0:
            raise LookupError("Dataset not found.")
        row = connection.execute(
            "SELECT * FROM datasets WHERE id=?", (dataset_id,)
        ).fetchone()
    audit(
        "dataset_policy_changed",
        actor_id=actor["id"],
        resource_type="dataset",
        resource_id=dataset_id,
        metadata={"visibility": visibility, "classification": classification},
    )
    return dict(row)


def set_dataset_grant(
    actor: dict,
    dataset_id: str,
    principal_type: str,
    principal_id: str,
    permissions: list[str],
    columns: list[str],
) -> None:
    if actor["role"] != "ADMIN":
        raise PermissionError("Administrator access is required.")
    if principal_type not in ("user", "role"):
        raise ValueError("Grant principal must be a user or role.")
    if principal_type == "role" and principal_id not in ROLES:
        raise ValueError("Invalid role.")
    if any(permission not in DATASET_PERMISSIONS for permission in permissions):
        raise ValueError("Invalid dataset permission.")
    dataset = dataset_policy(dataset_id)
    if dataset is None:
        raise LookupError("Dataset not found.")
    try:
        approved_columns = json.loads(dataset["columns_json"])
    except (TypeError, json.JSONDecodeError):
        approved_columns = []
    if any(column not in approved_columns for column in columns):
        raise ValueError("Grant contains an unknown dataset column.")
    with get_connection() as connection:
        if principal_type == "user" and connection.execute(
            "SELECT 1 FROM users WHERE id=? AND active=1", (principal_id,)
        ).fetchone() is None:
            raise ValueError("Active user not found.")
        connection.execute(
            """
            INSERT INTO dataset_grants
                (dataset_id, principal_type, principal_id,
                 permissions_json, columns_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id, principal_type, principal_id)
            DO UPDATE SET permissions_json=excluded.permissions_json,
                          columns_json=excluded.columns_json
            """,
            (
                dataset_id,
                principal_type,
                principal_id,
                json.dumps(sorted(set(permissions))),
                json.dumps(sorted(set(columns))),
            ),
        )
    audit(
        "dataset_permission_changed",
        actor_id=actor["id"],
        resource_type="dataset",
        resource_id=dataset_id,
        metadata={"principal_type": principal_type, "principal_id": principal_id, "permissions": permissions, "columns": columns},
    )


def dataset_access(user: dict, dataset_id: str) -> tuple[dict, set[str]] | None:
    dataset = dataset_policy(dataset_id)
    if dataset is None or dataset["archived_at"] is not None:
        return None
    if user["role"] == "ADMIN" or dataset["owner_id"] == user["id"]:
        return dataset, set(json.loads(dataset["columns_json"]))
    if dataset["visibility"] == "organization":
        return dataset, set(json.loads(dataset["columns_json"]))
    permitted_columns: set[str] = set()
    granted = False
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT permissions_json, columns_json FROM dataset_grants
            WHERE dataset_id=? AND (
                (principal_type='user' AND principal_id=?) OR
                (principal_type='role' AND principal_id=?)
            )
            """,
            (dataset_id, user["id"], user["role"]),
        ).fetchall()
    for row in rows:
        try:
            if "query" in json.loads(row["permissions_json"]):
                granted = True
                permitted_columns.update(json.loads(row["columns_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
    if not granted:
        return None
    return dataset, permitted_columns


def accessible_conversation(user: dict, conversation_id: str) -> bool:
    if user["role"] == "ADMIN":
        with get_connection() as connection:
            return connection.execute(
                "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone() is not None
    with get_connection() as connection:
        return connection.execute(
            "SELECT 1 FROM conversations WHERE id=? AND owner_id=?",
            (conversation_id, user["id"]),
        ).fetchone() is not None


def register_conversation(conversation_id: str, owner_id: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO conversations(id, owner_id) VALUES (?, ?)",
            (conversation_id, owner_id),
        )


def list_user_conversations(user: dict, list_all) -> list[dict]:
    rows = list_all()
    with get_connection() as connection:
        owners = {
            row["id"]: row["owner_id"]
            for row in connection.execute(
                "SELECT id, owner_id FROM conversations"
            ).fetchall()
        }
    return [
        row
        for row in rows
        if owners.get(row["id"]) == user["id"]
        or (user["role"] == "ADMIN" and row["id"] in owners)
    ]


def remove_conversation_mapping(user: dict, conversation_id: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM conversations WHERE id=? AND owner_id=?",
            (conversation_id, user["id"]),
        )


def overview() -> dict:
    with get_connection() as connection:
        user_counts = connection.execute(
            "SELECT COUNT(*) total, SUM(active) active FROM users"
        ).fetchone()
        docs = connection.execute(
            "SELECT COUNT(*) total FROM documents WHERE archived_at IS NULL"
        ).fetchone()[0]
        datasets = connection.execute(
            "SELECT COUNT(*) total FROM datasets WHERE classification='restricted' AND archived_at IS NULL"
        ).fetchone()[0]
        recent = connection.execute(
            """
            SELECT id, timestamp, actor_id, event_type, resource_type,
                   resource_id, result, metadata_json
            FROM audit_events ORDER BY timestamp DESC LIMIT 10
            """
        ).fetchall()
        settings = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key, value FROM settings")
        }
    return {
        "total_users": user_counts["total"] or 0,
        "active_users": user_counts["active"] or 0,
        "protected_documents": docs,
        "restricted_datasets": datasets,
        "recent_events": [dict(row) for row in recent],
        "setup_complete": True,
        "session_ttl_hours": SESSION_TTL_HOURS,
        "cookie_secure": COOKIE_SECURE,
        "csrf_protection": True,
        "login_lockout_threshold": 5,
        "legacy_import_complete": settings.get("legacy_import_complete") == "1",
    }


def audit_search(
    *,
    search: str = "",
    event_type: str = "",
    actor_id: str = "",
    resource_type: str = "",
    start_date: str = "",
    end_date: str = "",
    page: int = 1,
    page_size: int = 25,
    resource_ids: list[str] | None = None,
) -> dict:
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    where = []
    params: list[str | int] = []
    if search:
        where.append("(event_type LIKE ? OR resource_type LIKE ? OR resource_id LIKE ? OR result LIKE ?)")
        search_value = f"%{search[:120]}%"
        params.extend([search_value] * 4)
    for column, value in (
        ("event_type", event_type),
        ("actor_id", actor_id),
        ("resource_type", resource_type),
    ):
        if value:
            where.append(f"{column}=?")
            params.append(value[:120])
    if start_date:
        where.append("timestamp>=?")
        params.append(start_date[:40])
    if end_date:
        end_value = end_date[:40]
        if len(end_value) == 10:
            end_value += "T23:59:59.999999+00:00"
        where.append("timestamp<=?")
        params.append(end_value)
    if resource_ids is not None:
        if not resource_ids:
            return {"events": [], "total": 0, "page": page, "page_size": page_size}
        placeholders = ",".join("?" for _ in resource_ids[:500])
        where.append(f"resource_id IN ({placeholders})")
        params.extend(resource_ids[:500])
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with get_connection() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM audit_events{clause}", params
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT id, timestamp, actor_id, event_type, resource_type,
                   resource_id, result, metadata_json, request_id
            FROM audit_events{clause}
            ORDER BY timestamp DESC LIMIT ? OFFSET ?
            """,
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {"events": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def set_retention_days(actor: dict, days: int | None) -> None:
    if actor["role"] != "ADMIN":
        raise PermissionError("Administrator access is required.")
    if days is not None and not 1 <= days <= 36500:
        raise ValueError("Retention period must be between 1 and 36500 days.")
    value = "" if days is None else str(days)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES ('retention_days', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (value, timestamp()),
        )
    audit(
        "retention_policy_changed",
        actor_id=actor["id"],
        resource_type="governance",
        metadata={"retention_days": days},
    )


def retention_preview() -> dict:
    with get_connection() as connection:
        setting = connection.execute(
            "SELECT value FROM settings WHERE key='retention_days'"
        ).fetchone()
        docs = connection.execute(
            """
            SELECT id, owner_id, visibility, classification, uploaded_at, archived_at
            FROM documents WHERE archived_at IS NULL ORDER BY uploaded_at
            """
        ).fetchall()
    days = int(setting["value"]) if setting and setting["value"] else None
    today = utc_now()
    affected = []
    if days is not None:
        for doc in docs:
            if not doc["uploaded_at"]:
                continue
            try:
                expires = datetime.fromisoformat(doc["uploaded_at"]) + timedelta(days=days)
            except ValueError:
                continue
            if expires <= today:
                affected.append(
                    {
                        "document_id": doc["id"],
                        "classification": doc["classification"],
                        "uploaded_at": doc["uploaded_at"],
                        "expires_at": timestamp(expires),
                        "reason": f"Retention period of {days} days has elapsed.",
                    }
                )
    return {"retention_days": days, "affected_documents": affected, "count": len(affected)}


def mark_archived(actor: dict, document_ids: list[str]) -> int:
    if actor["role"] != "ADMIN":
        raise PermissionError("Administrator access is required.")
    if not document_ids or len(document_ids) > 500:
        raise ValueError("Select between 1 and 500 documents.")
    now = timestamp()
    with get_connection() as connection:
        placeholders = ",".join("?" for _ in document_ids)
        cursor = connection.execute(
            f"""
            UPDATE documents SET archived_at=?
            WHERE id IN ({placeholders}) AND archived_at IS NULL
            """,
            [now, *document_ids],
        )
    audit(
        "retention_archived",
        actor_id=actor["id"],
        resource_type="document",
        result="success",
        metadata={"count": cursor.rowcount, "document_ids": document_ids[:50]},
    )
    return cursor.rowcount


def remove_document_record(actor: dict, document_id: str) -> None:
    if actor["role"] != "ADMIN" and not can_access_document(
        actor, document_id, "delete"
    ):
        raise PermissionError("You cannot delete this document.")
    with get_connection() as connection:
        connection.execute("DELETE FROM documents WHERE id=?", (document_id,))


def security_status() -> dict:
    return {
        "setup_required": is_setup_required(),
        "session_ttl_hours": SESSION_TTL_HOURS,
        "cookie_secure": COOKIE_SECURE,
    }
