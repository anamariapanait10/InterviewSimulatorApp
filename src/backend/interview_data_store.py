from __future__ import annotations

import os
import sys
import aiosqlite
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InterviewSessionModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    resume_link: str | None = None
    resume_text: str | None = None
    proceed_without_resume: bool = False
    job_description_link: str | None = None
    job_description_text: str | None = None
    proceed_without_job_description: bool = False
    transcript: str | None = None
    is_completed: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SessionTurnUpdate(BaseModel):
    user_message: str
    assistant_message: str
    resume_link: str | None = None
    job_description_link: str | None = None


DATABASE_PATH = os.getenv("DATABASE_PATH", "./interviewcoach.db")


def _row_to_model(row: aiosqlite.Row) -> InterviewSessionModel:
    def parse_dt(value: str | None) -> datetime:
        if not value:
            return utcnow()
        return datetime.fromisoformat(value)

    return InterviewSessionModel(
        id=UUID(row["id"]),
        resume_link=row["resume_link"],
        resume_text=row["resume_text"],
        proceed_without_resume=bool(row["proceed_without_resume"]),
        job_description_link=row["job_description_link"],
        job_description_text=row["job_description_text"],
        proceed_without_job_description=bool(row["proceed_without_job_description"]),
        transcript=row["transcript"],
        is_completed=bool(row["is_completed"]),
        created_at=parse_dt(row["created_at"]),
        updated_at=parse_dt(row["updated_at"]),
    )


class InterviewSessionRepository:
    async def init_db(self) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS InterviewSessions (
                    id TEXT PRIMARY KEY,
                    resume_link TEXT,
                    resume_text TEXT,
                    proceed_without_resume INTEGER NOT NULL DEFAULT 0,
                    job_description_link TEXT,
                    job_description_text TEXT,
                    proceed_without_job_description INTEGER NOT NULL DEFAULT 0,
                    transcript TEXT,
                    is_completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await conn.commit()

    async def add_interview_session(self, record: InterviewSessionModel) -> InterviewSessionModel:
        now = utcnow()
        print(f"Adding session {record.id}", file=sys.stderr)
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                INSERT OR IGNORE INTO InterviewSessions (
                    id, resume_link, resume_text, proceed_without_resume,
                    job_description_link, job_description_text, proceed_without_job_description,
                    transcript, is_completed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.id),
                    record.resume_link,
                    record.resume_text,
                    int(record.proceed_without_resume),
                    record.job_description_link,
                    record.job_description_text,
                    int(record.proceed_without_job_description),
                    record.transcript,
                    int(record.is_completed),
                    (record.created_at or now).isoformat(),
                    (record.updated_at or now).isoformat(),
                ),
            )
            print(f"Session {record.id} added, committing to database", file=sys.stderr)
            await conn.commit()
            print(f"Session {record.id} committed to database", file=sys.stderr)

        print(f"Retrieving session {record.id} after insertion", file=sys.stderr)
        existing = await self.get_interview_session(record.id)
        print(f"Retrieved session {record.id} after insertion: {existing is not None}", file=sys.stderr)
        if existing is None:
            raise RuntimeError("Failed to insert interview session")
        return existing

    async def get_all_interview_sessions(self) -> list[InterviewSessionModel]:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM InterviewSessions ORDER BY created_at ASC")
            rows = await cursor.fetchall()
            return [_row_to_model(r) for r in rows]

    async def get_interview_session(self, session_id: UUID) -> InterviewSessionModel | None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM InterviewSessions WHERE id = ?", (str(session_id),))
            row = await cursor.fetchone()
            return _row_to_model(row) if row else None

    async def update_interview_session(self, record: InterviewSessionModel) -> InterviewSessionModel | None:
        existing = await self.get_interview_session(record.id)
        if existing is None:
            return None

        merged_transcript = (
            f"{(existing.transcript or '').strip()}\n\n{(record.transcript or '').strip()}".strip()
            if (existing.transcript or record.transcript)
            else None
        )

        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                UPDATE InterviewSessions
                SET resume_link = ?,
                    resume_text = ?,
                    proceed_without_resume = ?,
                    job_description_link = ?,
                    job_description_text = ?,
                    proceed_without_job_description = ?,
                    transcript = ?,
                    is_completed = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    record.resume_link,
                    record.resume_text,
                    int(record.proceed_without_resume),
                    record.job_description_link,
                    record.job_description_text,
                    int(record.proceed_without_job_description),
                    merged_transcript,
                    int(record.is_completed),
                    utcnow().isoformat(),
                    str(record.id),
                ),
            )
            await conn.commit()

        return await self.get_interview_session(record.id)

    async def complete_interview_session(self, session_id: UUID) -> InterviewSessionModel | None:
        current = await self.get_interview_session(session_id)
        if current is None:
            return None

        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                "UPDATE InterviewSessions SET is_completed = 1, updated_at = ? WHERE id = ?",
                (utcnow().isoformat(), str(session_id)),
            )
            await conn.commit()

        return await self.get_interview_session(session_id)

    async def ensure_session(self, session_id: UUID) -> InterviewSessionModel:
        print(f"22 Ensuring session {session_id}", file=sys.stderr)
        existing = await self.get_interview_session(session_id)
        print(f"33 Ensuring session {session_id}, existing: {existing is not None}", file=sys.stderr)
        if existing is not None:
            return existing
        
        print(f"44 Creating session {session_id}", file=sys.stderr)
        return await self.add_interview_session(InterviewSessionModel(id=session_id))

    async def append_turn(self, session_id: UUID, payload: SessionTurnUpdate) -> InterviewSessionModel:
        session = await self.ensure_session(session_id)
        update_record = InterviewSessionModel(
            id=session.id,
            resume_link=payload.resume_link or session.resume_link,
            resume_text=session.resume_text,
            proceed_without_resume=session.proceed_without_resume,
            job_description_link=payload.job_description_link or session.job_description_link,
            job_description_text=session.job_description_text,
            proceed_without_job_description=session.proceed_without_job_description,
            transcript=(
                f"User: {payload.user_message.strip()}\n"
                f"Assistant: {payload.assistant_message.strip()}"
            ),
            is_completed=session.is_completed,
        )
        updated = await self.update_interview_session(update_record)
        if updated is None:
            raise RuntimeError("Failed to update interview session")
        return updated
