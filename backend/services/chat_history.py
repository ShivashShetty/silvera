
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "chat_history.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def initialize_database():
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL
                    CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS
                idx_messages_conversation
            ON messages(conversation_id, created_at);
            """
        )


def current_timestamp():
    return datetime.now(timezone.utc).isoformat()


def create_conversation(first_question):
    question = first_question.strip()

    if not question:
        raise ValueError("The first question cannot be empty.")

    conversation_id = str(uuid4())
    now = current_timestamp()

    # Use the first question as the title.
    title = " ".join(question.split())
    if len(title) > 60:
        title = title[:57].rstrip() + "..."

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO conversations
                (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, title, now, now),
        )

    return conversation_id


def conversation_exists(conversation_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()

    return row is not None


def save_message(
    conversation_id,
    role,
    content,
    sources=None,
):
    if role not in ("user", "assistant"):
        raise ValueError("Invalid message role.")

    message_id = str(uuid4())
    now = current_timestamp()
    sources_json = json.dumps(
        sources or [],
        ensure_ascii=False,
    )

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO messages (
                id,
                conversation_id,
                role,
                content,
                sources_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                role,
                content,
                sources_json,
                now,
            ),
        )

        connection.execute(
            """
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
            """,
            (now, conversation_id),
        )

    return {
        "id": message_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "sources": sources or [],
        "created_at": now,
    }


def list_conversations():
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                c.id,
                c.title,
                c.created_at,
                c.updated_at,
                COUNT(m.id) AS message_count
            FROM conversations AS c
            LEFT JOIN messages AS m
                ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_conversation(conversation_id):
    with get_connection() as connection:
        conversation = connection.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        ).fetchone()

        if conversation is None:
            return None

        rows = connection.execute(
            """
            SELECT id, role, content, sources_json, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (conversation_id,),
        ).fetchall()

    messages = []

    for row in rows:
        message = dict(row)
        raw_sources = message.pop("sources_json")

        try:
            message["sources"] = json.loads(raw_sources)
        except (json.JSONDecodeError, TypeError):
            message["sources"] = []

        messages.append(message)

    return {
        **dict(conversation),
        "messages": messages,
    }


def delete_conversation(conversation_id):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )

    return cursor.rowcount > 0
