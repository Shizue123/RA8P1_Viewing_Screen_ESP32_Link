from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from cloud.app.config import Settings


_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=32768, parallelism=2)
_PASSWORD_MIN_LENGTH = 6


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=256)


class CreateUserRequest(LoginRequest):
    role: str = Field(default="member", pattern=r"^(admin|member)$")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=256)
    new_password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=256)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    role: str
    csrf_token: str
    hermes_session_id: str

    def public(self) -> dict[str, object]:
        return {"id": self.id, "username": self.username, "role": self.role}


class AuthStore:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._db_path = self._resolve_db_path(settings.auth_db_path)
        self._ensure_schema()

    @staticmethod
    def _resolve_db_path(value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self._db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS web_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'member')),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until INTEGER NOT NULL DEFAULT 0,
                    hermes_session_id TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    last_login_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS web_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    csrf_token TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_web_sessions_user_id ON web_sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_web_sessions_expires_at ON web_sessions(expires_at);

                CREATE TABLE IF NOT EXISTS web_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_id TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    is_pinned INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_web_conversations_user_id
                    ON web_conversations(user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS web_chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    conversation_id INTEGER,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE,
                    FOREIGN KEY(conversation_id) REFERENCES web_conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_web_chat_messages_user_id
                    ON web_chat_messages(user_id, id);
                """
            )
            message_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(web_chat_messages)").fetchall()
            }
            if "conversation_id" not in message_columns:
                connection.execute("ALTER TABLE web_chat_messages ADD COLUMN conversation_id INTEGER")
            conversation_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(web_conversations)").fetchall()
            }
            if "is_pinned" not in conversation_columns:
                connection.execute(
                    "ALTER TABLE web_conversations ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_chat_messages_conversation_id
                ON web_chat_messages(conversation_id, id)
                """
            )
            self._migrate_legacy_messages(connection)

    @staticmethod
    def _migrate_legacy_messages(connection: sqlite3.Connection) -> None:
        user_rows = connection.execute(
            """
            SELECT DISTINCT user_id
            FROM web_chat_messages
            WHERE conversation_id IS NULL
            """
        ).fetchall()
        for user_row in user_rows:
            user_id = int(user_row["user_id"])
            timestamps = connection.execute(
                """
                SELECT MIN(created_at) AS created_at, MAX(created_at) AS updated_at
                FROM web_chat_messages
                WHERE user_id = ? AND conversation_id IS NULL
                """,
                (user_id,),
            ).fetchone()
            cursor = connection.execute(
                """
                INSERT INTO web_conversations
                    (public_id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    secrets.token_urlsafe(18),
                    user_id,
                    "历史对话",
                    int(timestamps["created_at"] or time.time()),
                    int(timestamps["updated_at"] or time.time()),
                ),
            )
            connection.execute(
                """
                UPDATE web_chat_messages
                SET conversation_id = ?
                WHERE user_id = ? AND conversation_id IS NULL
                """,
                (int(cursor.lastrowid), user_id),
            )

    def bootstrap_required(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM web_users").fetchone()
        return not row or int(row["total"]) == 0

    def create_user(self, username: str, password: str, role: str) -> dict[str, object]:
        now = int(time.time())
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO web_users (username, password_hash, role, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (username.strip(), _PASSWORD_HASHER.hash(password), role, now),
                )
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="username already exists") from exc
        return {"id": user_id, "username": username.strip(), "role": role}

    def register_first_admin(self, username: str, password: str) -> dict[str, object]:
        if not self.bootstrap_required():
            raise HTTPException(status_code=403, detail="bootstrap registration is closed")
        return self.create_user(username, password, "admin")

    def login(self, username: str, password: str) -> tuple[str, AuthenticatedUser]:
        now = int(time.time())
        auth_error: HTTPException | None = None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM web_users WHERE username = ? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()

            if not row or not bool(row["is_active"]):
                raise HTTPException(status_code=401, detail="invalid username or password")
            if int(row["locked_until"]) > now:
                raise HTTPException(status_code=423, detail="account temporarily locked")

            try:
                _PASSWORD_HASHER.verify(str(row["password_hash"]), password)
            except VerificationError:
                failures = int(row["failed_attempts"]) + 1
                locked_until = now + 900 if failures >= 5 else 0
                connection.execute(
                    "UPDATE web_users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (0 if locked_until else failures, locked_until, int(row["id"])),
                )
                auth_error = HTTPException(status_code=401, detail="invalid username or password")
            if auth_error is None and _PASSWORD_HASHER.check_needs_rehash(str(row["password_hash"])):
                connection.execute(
                    "UPDATE web_users SET password_hash = ? WHERE id = ?",
                    (_PASSWORD_HASHER.hash(password), int(row["id"])),
                )
            if auth_error is None:
                connection.execute(
                    """
                    UPDATE web_users
                    SET failed_attempts = 0, locked_until = 0, last_login_at = ?
                    WHERE id = ?
                    """,
                    (now, int(row["id"])),
                )
        if auth_error is not None:
            raise auth_error

        token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + max(1, self._settings.auth_session_ttl_hours) * 3600
        with self._connect() as connection:
            connection.execute("DELETE FROM web_sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                """
                INSERT INTO web_sessions
                    (token_hash, user_id, csrf_token, created_at, expires_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (_token_hash(token), int(row["id"]), csrf_token, now, expires_at, now),
            )
        return token, AuthenticatedUser(
            id=int(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            csrf_token=csrf_token,
            hermes_session_id=str(row["hermes_session_id"] or ""),
        )

    def authenticate(self, request: Request, *, require_csrf: bool = False) -> AuthenticatedUser:
        token = request.cookies.get(self._settings.auth_cookie_name, "")
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")

        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    u.id, u.username, u.role, u.is_active, u.hermes_session_id,
                    s.csrf_token, s.expires_at
                FROM web_sessions s
                JOIN web_users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (_token_hash(token),),
            ).fetchone()
            if not row or not bool(row["is_active"]) or int(row["expires_at"]) <= now:
                if row:
                    connection.execute("DELETE FROM web_sessions WHERE token_hash = ?", (_token_hash(token),))
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired")
            connection.execute(
                "UPDATE web_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now, _token_hash(token)),
            )

        if require_csrf:
            supplied = request.headers.get("x-csrf-token", "")
            if not supplied or not hmac.compare_digest(supplied, str(row["csrf_token"])):
                raise HTTPException(status_code=403, detail="invalid CSRF token")

        return AuthenticatedUser(
            id=int(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            csrf_token=str(row["csrf_token"]),
            hermes_session_id=str(row["hermes_session_id"] or ""),
        )

    def logout(self, request: Request) -> None:
        token = request.cookies.get(self._settings.auth_cookie_name, "")
        if token:
            with self._connect() as connection:
                connection.execute("DELETE FROM web_sessions WHERE token_hash = ?", (_token_hash(token),))

    def list_users(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, username, role, is_active, created_at, last_login_at
                FROM web_users ORDER BY created_at ASC
                """
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "username": str(row["username"]),
                "role": str(row["role"]),
                "is_active": bool(row["is_active"]),
                "created_at": int(row["created_at"]),
                "last_login_at": row["last_login_at"],
            }
            for row in rows
        ]

    def delete_user(self, admin: AuthenticatedUser, target_user_id: int) -> dict[str, object]:
        with self._connect() as connection:
            target = connection.execute(
                """
                SELECT id, username, role, is_active
                FROM web_users
                WHERE id = ?
                """,
                (target_user_id,),
            ).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="user not found")
            if int(target["id"]) == admin.id:
                raise HTTPException(status_code=400, detail="cannot delete current account")
            if str(target["role"]) == "admin":
                admin_count = connection.execute(
                    "SELECT COUNT(*) AS total FROM web_users WHERE role = 'admin'",
                ).fetchone()
                if admin_count and int(admin_count["total"]) <= 1:
                    raise HTTPException(status_code=400, detail="at least one administrator must remain")

            connection.execute("DELETE FROM web_sessions WHERE user_id = ?", (int(target["id"]),))
            connection.execute("DELETE FROM web_chat_messages WHERE user_id = ?", (int(target["id"]),))
            connection.execute("DELETE FROM web_conversations WHERE user_id = ?", (int(target["id"]),))
            connection.execute("DELETE FROM web_users WHERE id = ?", (int(target["id"]),))
        return {
            "id": int(target["id"]),
            "username": str(target["username"]),
            "role": str(target["role"]),
            "is_active": bool(target["is_active"]),
        }

    def change_password(self, user: AuthenticatedUser, current_password: str, new_password: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM web_users WHERE id = ?",
                (user.id,),
            ).fetchone()
            try:
                if not row:
                    raise VerifyMismatchError
                _PASSWORD_HASHER.verify(str(row["password_hash"]), current_password)
            except VerificationError as exc:
                raise HTTPException(status_code=401, detail="current password is incorrect") from exc
            connection.execute(
                "UPDATE web_users SET password_hash = ? WHERE id = ?",
                (_PASSWORD_HASHER.hash(new_password), user.id),
            )
            connection.execute("DELETE FROM web_sessions WHERE user_id = ?", (user.id,))

    def set_hermes_session(self, user_id: int, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE web_users SET hermes_session_id = ? WHERE id = ?",
                (session_id, user_id),
            )

    def create_conversation(self, user_id: int, title: str = "新对话") -> dict[str, object]:
        now = int(time.time())
        public_id = secrets.token_urlsafe(18)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO web_conversations
                    (public_id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (public_id, user_id, title.strip()[:80] or "新对话", now, now),
            )
            conversation_id = int(cursor.lastrowid)
        return {
            "id": public_id,
            "title": title.strip()[:80] or "新对话",
            "is_pinned": False,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
            "_internal_id": conversation_id,
        }

    def list_conversations(self, user_id: int) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.public_id, c.title, c.is_pinned, c.created_at, c.updated_at,
                    COUNT(m.id) AS message_count
                FROM web_conversations c
                LEFT JOIN web_chat_messages m ON m.conversation_id = c.id
                WHERE c.user_id = ?
                GROUP BY c.id
                ORDER BY c.is_pinned DESC, c.updated_at DESC, c.id DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "id": str(row["public_id"]),
                "title": str(row["title"]),
                "is_pinned": bool(row["is_pinned"]),
                "created_at": int(row["created_at"]),
                "updated_at": int(row["updated_at"]),
                "message_count": int(row["message_count"]),
            }
            for row in rows
        ]

    def conversation_for_user(self, user_id: int, public_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, public_id, title, is_pinned, created_at, updated_at
                FROM web_conversations
                WHERE user_id = ? AND public_id = ?
                """,
                (user_id, public_id),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "internal_id": int(row["id"]),
            "id": str(row["public_id"]),
            "title": str(row["title"]),
            "is_pinned": bool(row["is_pinned"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
        }

    def delete_conversation(self, user_id: int, public_id: str) -> None:
        conversation = self.conversation_for_user(user_id, public_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM web_conversations WHERE id = ? AND user_id = ?",
                (conversation["internal_id"], user_id),
            )

    def rename_conversation(self, user_id: int, public_id: str, title: str) -> dict[str, object]:
        conversation = self.conversation_for_user(user_id, public_id)
        clean_title = " ".join(title.split())[:80]
        if not clean_title:
            raise HTTPException(status_code=422, detail="conversation title is required")
        with self._connect() as connection:
            connection.execute(
                "UPDATE web_conversations SET title = ?, updated_at = ? WHERE id = ?",
                (clean_title, int(time.time()), conversation["internal_id"]),
            )
        return {"id": public_id, "title": clean_title}

    def set_conversation_pinned(
        self,
        user_id: int,
        public_id: str,
        is_pinned: bool,
    ) -> dict[str, object]:
        conversation = self.conversation_for_user(user_id, public_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE web_conversations SET is_pinned = ? WHERE id = ?",
                (1 if is_pinned else 0, conversation["internal_id"]),
            )
        return {"id": public_id, "is_pinned": is_pinned}

    def append_chat_message(
        self,
        user_id: int,
        conversation_public_id: str,
        role: str,
        content: str,
    ) -> None:
        conversation = self.conversation_for_user(user_id, conversation_public_id)
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO web_chat_messages
                    (user_id, conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, conversation["internal_id"], role, content, now),
            )
            if role == "user":
                message_count = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM web_chat_messages
                    WHERE conversation_id = ? AND role = 'user'
                    """,
                    (conversation["internal_id"],),
                ).fetchone()
                if int(message_count["total"]) == 1:
                    title = " ".join(content.split())[:42] or "新对话"
                    connection.execute(
                        "UPDATE web_conversations SET title = ? WHERE id = ?",
                        (title, conversation["internal_id"]),
                    )
            connection.execute(
                "UPDATE web_conversations SET updated_at = ? WHERE id = ?",
                (now, conversation["internal_id"]),
            )

    def chat_history(
        self,
        user_id: int,
        conversation_public_id: str,
        limit: int = 80,
    ) -> list[dict[str, object]]:
        bounded_limit = max(1, min(limit, 200))
        conversation = self.conversation_for_user(user_id, conversation_public_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, created_at
                FROM web_chat_messages
                WHERE user_id = ? AND conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, conversation["internal_id"], bounded_limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "created_at": int(row["created_at"]),
            }
            for row in reversed(rows)
        ]


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=max(1, settings.auth_session_ttl_hours) * 3600,
        httponly=True,
        secure=settings.app_env.lower() in {"prod", "production"},
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(key=settings.auth_cookie_name, path="/")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
