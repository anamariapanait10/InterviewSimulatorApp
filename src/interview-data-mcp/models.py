from __future__ import annotations

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