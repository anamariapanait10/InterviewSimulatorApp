from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from db import InterviewSessionORM, SessionLocal
from models import InterviewSessionModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def orm_to_model(row: InterviewSessionORM) -> InterviewSessionModel:
    return InterviewSessionModel(
        id=UUID(row.id),
        resume_link=row.resume_link,
        resume_text=row.resume_text,
        proceed_without_resume=row.proceed_without_resume,
        job_description_link=row.job_description_link,
        job_description_text=row.job_description_text,
        proceed_without_job_description=row.proceed_without_job_description,
        transcript=row.transcript,
        is_completed=row.is_completed,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class InterviewSessionRepository:
    async def add_interview_session(self, record: InterviewSessionModel) -> InterviewSessionModel:
        async with SessionLocal() as session:
            row = InterviewSessionORM(
                id=str(record.id),
                resume_link=record.resume_link,
                resume_text=record.resume_text,
                proceed_without_resume=record.proceed_without_resume,
                job_description_link=record.job_description_link,
                job_description_text=record.job_description_text,
                proceed_without_job_description=record.proceed_without_job_description,
                transcript=record.transcript,
                is_completed=record.is_completed,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return orm_to_model(row)

    async def get_all_interview_sessions(self) -> list[InterviewSessionModel]:
        async with SessionLocal() as session:
            result = await session.execute(select(InterviewSessionORM))
            rows = result.scalars().all()
            return [orm_to_model(r) for r in rows]

    async def get_interview_session(self, session_id: UUID) -> InterviewSessionModel | None:
        async with SessionLocal() as session:
            row = await session.get(InterviewSessionORM, str(session_id))
            return orm_to_model(row) if row else None

    async def update_interview_session(self, record: InterviewSessionModel) -> InterviewSessionModel | None:
        async with SessionLocal() as session:
            row = await session.get(InterviewSessionORM, str(record.id))
            if row is None:
                return None

            row.resume_link = record.resume_link
            row.resume_text = record.resume_text
            row.proceed_without_resume = record.proceed_without_resume
            row.job_description_link = record.job_description_link
            row.job_description_text = record.job_description_text
            row.proceed_without_job_description = record.proceed_without_job_description
            row.updated_at = _utcnow()

            existing = row.transcript or ""
            incoming = record.transcript or ""
            row.transcript = f"{existing}\n\n{incoming}".strip() if (existing or incoming) else None

            await session.commit()
            await session.refresh(row)
            return orm_to_model(row)

    async def complete_interview_session(self, session_id: UUID) -> InterviewSessionModel | None:
        async with SessionLocal() as session:
            row = await session.get(InterviewSessionORM, str(session_id))
            if row is None:
                return None

            row.is_completed = True
            await session.commit()
            await session.refresh(row)
            return orm_to_model(row)