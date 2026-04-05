from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import aiosqlite
from pydantic import BaseModel, Field


DATABASE_PATH = os.getenv("DATABASE_PATH", "./interviewcoach.db")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    email: str
    created_at: datetime = Field(default_factory=utcnow)


class UserRecordModel(UserModel):
    password_hash: str


class AuthTokenModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    token: str
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return utcnow()
    return datetime.fromisoformat(value)


def _row_to_user(row: aiosqlite.Row) -> UserRecordModel:
    return UserRecordModel(
        id=UUID(row["id"]),
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=_parse_datetime(row["created_at"]),
    )


class AuthRepository:
    async def init_db(self) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS Users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS AuthTokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            await conn.commit()

    async def create_user(self, email: str, password_hash: str) -> UserModel:
        user = UserRecordModel(email=email, password_hash=password_hash)
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                INSERT INTO Users (id, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(user.id), user.email, user.password_hash, user.created_at.isoformat()),
            )
            await conn.commit()
        return UserModel.model_validate(user.model_dump())

    async def get_user_by_email(self, email: str) -> UserRecordModel | None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM Users WHERE email = ?", (email,))
            row = await cursor.fetchone()
            return _row_to_user(row) if row else None

    async def get_user_by_id(self, user_id: UUID) -> UserRecordModel | None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM Users WHERE id = ?", (str(user_id),))
            row = await cursor.fetchone()
            return _row_to_user(row) if row else None

    async def issue_token(self, user_id: UUID, token: str, duration_days: int = 7) -> AuthTokenModel:
        auth_token = AuthTokenModel(
            user_id=user_id,
            token=token,
            expires_at=utcnow() + timedelta(days=duration_days),
        )
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                INSERT INTO AuthTokens (id, user_id, token, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(auth_token.id),
                    str(auth_token.user_id),
                    auth_token.token,
                    auth_token.created_at.isoformat(),
                    auth_token.expires_at.isoformat(),
                ),
            )
            await conn.commit()
        return auth_token

    async def get_user_by_token(self, token: str) -> UserModel | None:
        now = utcnow().isoformat()
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT Users.*
                FROM AuthTokens
                INNER JOIN Users ON Users.id = AuthTokens.user_id
                WHERE AuthTokens.token = ? AND AuthTokens.expires_at > ?
                """,
                (token, now),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            user = _row_to_user(row)
            return UserModel.model_validate(user.model_dump())

    async def delete_token(self, token: str) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute("DELETE FROM AuthTokens WHERE token = ?", (token,))
            await conn.commit()

    async def delete_expired_tokens(self) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute("DELETE FROM AuthTokens WHERE expires_at <= ?", (utcnow().isoformat(),))
            await conn.commit()
