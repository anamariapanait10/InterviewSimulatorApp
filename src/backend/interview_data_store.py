from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

import aiosqlite
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InterviewQuestionModel(BaseModel):
    id: str
    order: int
    category: str
    prompt: str


class InterviewAnswerModel(BaseModel):
    question_id: str
    question_order: int
    category: str
    question_prompt: str
    answer_text: str
    submitted_at: datetime = Field(default_factory=utcnow)


class InterviewQuestionFeedbackModel(BaseModel):
    question_id: str
    score: int
    feedback: str


class InterviewReportModel(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    behavioral_feedback: str
    technical_feedback: str
    communication_feedback: str
    recommendation: str
    question_feedback: list[InterviewQuestionFeedbackModel] = Field(default_factory=list)


class InterviewSessionModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    resume_link: str | None = None
    resume_text: str | None = None
    proceed_without_resume: bool = False
    job_description_link: str | None = None
    job_description_text: str | None = None
    proceed_without_job_description: bool = False
    transcript: str | None = None
    interview_length: str | None = None
    role_title: str | None = None
    questions: list[InterviewQuestionModel] = Field(default_factory=list)
    answers: list[InterviewAnswerModel] = Field(default_factory=list)
    current_question_index: int = 0
    score: int | None = None
    report: InterviewReportModel | None = None
    is_completed: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


class SessionTurnUpdate(BaseModel):
    user_message: str
    assistant_message: str
    resume_link: str | None = None
    job_description_link: str | None = None
    resume_text: str | None = None
    job_description_text: str | None = None


DATABASE_PATH = os.getenv("DATABASE_PATH", "./interviewcoach.db")

OPTIONAL_COLUMNS: dict[str, str] = {
    "interview_length": "TEXT",
    "role_title": "TEXT",
    "questions_json": "TEXT NOT NULL DEFAULT '[]'",
    "answers_json": "TEXT NOT NULL DEFAULT '[]'",
    "current_question_index": "INTEGER NOT NULL DEFAULT 0",
    "score": "INTEGER",
    "report_json": "TEXT",
    "completed_at": "TEXT",
}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _json_default(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _load_json_list(raw: str | None, model_type: type[BaseModel]) -> list[Any]:
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(payload, list):
        return []

    parsed: list[Any] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed.append(model_type.model_validate(item))
    return parsed


def _load_json_object(raw: str | None, model_type: type[BaseModel]) -> BaseModel | None:
    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    return model_type.model_validate(payload)


def _serialize_questions(value: Iterable[InterviewQuestionModel]) -> str:
    return _json_default([item.model_dump(mode="json") for item in value])


def _serialize_answers(value: Iterable[InterviewAnswerModel]) -> str:
    return _json_default([item.model_dump(mode="json") for item in value])


def _serialize_report(value: InterviewReportModel | None) -> str | None:
    if value is None:
        return None
    return _json_default(value.model_dump(mode="json"))


def _row_to_model(row: aiosqlite.Row) -> InterviewSessionModel:
    created_at = _parse_datetime(row["created_at"]) or utcnow()
    updated_at = _parse_datetime(row["updated_at"]) or utcnow()

    return InterviewSessionModel(
        id=UUID(row["id"]),
        resume_link=row["resume_link"],
        resume_text=row["resume_text"],
        proceed_without_resume=bool(row["proceed_without_resume"]),
        job_description_link=row["job_description_link"],
        job_description_text=row["job_description_text"],
        proceed_without_job_description=bool(row["proceed_without_job_description"]),
        transcript=row["transcript"],
        interview_length=row["interview_length"],
        role_title=row["role_title"],
        questions=_load_json_list(row["questions_json"], InterviewQuestionModel),
        answers=_load_json_list(row["answers_json"], InterviewAnswerModel),
        current_question_index=int(row["current_question_index"] or 0),
        score=row["score"],
        report=_load_json_object(row["report_json"], InterviewReportModel),
        is_completed=bool(row["is_completed"]),
        created_at=created_at,
        updated_at=updated_at,
        completed_at=_parse_datetime(row["completed_at"]),
    )


class InterviewSessionRepository:
    async def _ensure_optional_columns(self, conn: aiosqlite.Connection) -> None:
        cursor = await conn.execute("PRAGMA table_info(InterviewSessions)")
        columns = {row[1] for row in await cursor.fetchall()}

        for name, definition in OPTIONAL_COLUMNS.items():
            if name in columns:
                continue
            await conn.execute(f"ALTER TABLE InterviewSessions ADD COLUMN {name} {definition}")

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
                    updated_at TEXT NOT NULL,
                    interview_length TEXT,
                    role_title TEXT,
                    questions_json TEXT NOT NULL DEFAULT '[]',
                    answers_json TEXT NOT NULL DEFAULT '[]',
                    current_question_index INTEGER NOT NULL DEFAULT 0,
                    score INTEGER,
                    report_json TEXT,
                    completed_at TEXT
                )
                """
            )
            await self._ensure_optional_columns(conn)
            await conn.commit()

    async def add_interview_session(self, record: InterviewSessionModel) -> InterviewSessionModel:
        now = utcnow()
        print(f"Adding session {record.id}", file=sys.stderr)
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                INSERT OR IGNORE INTO InterviewSessions (
                    id,
                    resume_link,
                    resume_text,
                    proceed_without_resume,
                    job_description_link,
                    job_description_text,
                    proceed_without_job_description,
                    transcript,
                    interview_length,
                    role_title,
                    questions_json,
                    answers_json,
                    current_question_index,
                    score,
                    report_json,
                    is_completed,
                    created_at,
                    updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    record.interview_length,
                    record.role_title,
                    _serialize_questions(record.questions),
                    _serialize_answers(record.answers),
                    record.current_question_index,
                    record.score,
                    _serialize_report(record.report),
                    int(record.is_completed),
                    (record.created_at or now).isoformat(),
                    (record.updated_at or now).isoformat(),
                    record.completed_at.isoformat() if record.completed_at else None,
                ),
            )
            await conn.commit()

        existing = await self.get_interview_session(record.id)
        if existing is None:
            raise RuntimeError("Failed to insert interview session")
        return existing

    async def get_all_interview_sessions(self) -> list[InterviewSessionModel]:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM InterviewSessions ORDER BY created_at DESC")
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

        explicit_fields = set(record.model_fields_set)

        def pick(field_name: str) -> Any:
            if field_name in explicit_fields:
                return getattr(record, field_name)
            return getattr(existing, field_name)

        transcript = existing.transcript
        if "transcript" in explicit_fields:
            incoming_transcript = (record.transcript or "").strip()
            if incoming_transcript:
                transcript = (
                    f"{(existing.transcript or '').strip()}\n\n{incoming_transcript}".strip()
                    if existing.transcript
                    else incoming_transcript
                )
            elif record.transcript is None:
                transcript = existing.transcript
            else:
                transcript = None

        updated_record = InterviewSessionModel(
            id=existing.id,
            resume_link=pick("resume_link"),
            resume_text=pick("resume_text"),
            proceed_without_resume=pick("proceed_without_resume"),
            job_description_link=pick("job_description_link"),
            job_description_text=pick("job_description_text"),
            proceed_without_job_description=pick("proceed_without_job_description"),
            transcript=transcript,
            interview_length=pick("interview_length"),
            role_title=pick("role_title"),
            questions=pick("questions"),
            answers=pick("answers"),
            current_question_index=pick("current_question_index"),
            score=pick("score"),
            report=pick("report"),
            is_completed=pick("is_completed"),
            created_at=existing.created_at,
            updated_at=utcnow(),
            completed_at=pick("completed_at"),
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
                    interview_length = ?,
                    role_title = ?,
                    questions_json = ?,
                    answers_json = ?,
                    current_question_index = ?,
                    score = ?,
                    report_json = ?,
                    is_completed = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    updated_record.resume_link,
                    updated_record.resume_text,
                    int(updated_record.proceed_without_resume),
                    updated_record.job_description_link,
                    updated_record.job_description_text,
                    int(updated_record.proceed_without_job_description),
                    updated_record.transcript,
                    updated_record.interview_length,
                    updated_record.role_title,
                    _serialize_questions(updated_record.questions),
                    _serialize_answers(updated_record.answers),
                    updated_record.current_question_index,
                    updated_record.score,
                    _serialize_report(updated_record.report),
                    int(updated_record.is_completed),
                    updated_record.updated_at.isoformat(),
                    updated_record.completed_at.isoformat() if updated_record.completed_at else None,
                    str(updated_record.id),
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
                """
                UPDATE InterviewSessions
                SET is_completed = 1,
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (utcnow().isoformat(), utcnow().isoformat(), str(session_id)),
            )
            await conn.commit()

        return await self.get_interview_session(session_id)

    async def ensure_session(self, session_id: UUID) -> InterviewSessionModel:
        existing = await self.get_interview_session(session_id)
        if existing is not None:
            return existing
        return await self.add_interview_session(InterviewSessionModel(id=session_id))

    async def append_turn(self, session_id: UUID, payload: SessionTurnUpdate) -> InterviewSessionModel:
        session = await self.ensure_session(session_id)
        updated = await self.update_interview_session(
            InterviewSessionModel(
                id=session.id,
                resume_link=payload.resume_link or session.resume_link,
                resume_text=payload.resume_text or session.resume_text,
                proceed_without_resume=session.proceed_without_resume,
                job_description_link=payload.job_description_link or session.job_description_link,
                job_description_text=payload.job_description_text or session.job_description_text,
                proceed_without_job_description=session.proceed_without_job_description,
                transcript=(
                    f"User: {payload.user_message.strip()}\n"
                    f"Assistant: {payload.assistant_message.strip()}"
                ),
            )
        )
        if updated is None:
            raise RuntimeError("Failed to update interview session")
        return updated
