from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Literal
from uuid import UUID, uuid4

import aiosqlite
from pydantic import BaseModel, Field

from coding_problem_bank import DEFAULT_CODING_PROBLEMS


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InterviewQuestionModel(BaseModel):
    id: str
    order: int
    category: Literal["behavioral", "technical"]
    prompt: str


class InterviewAnswerModel(BaseModel):
    question_id: str
    question_order: int
    category: Literal["behavioral", "technical"]
    question_prompt: str
    answer_text: str
    submitted_at: datetime = Field(default_factory=utcnow)


class InterviewQuestionFeedbackModel(BaseModel):
    question_id: str
    score: int
    feedback: str


class CodingProblemExampleModel(BaseModel):
    input: str
    output: str
    explanation: str | None = None


class CodingProblemModel(BaseModel):
    id: str
    title: str
    company: str
    difficulty: str
    prompt: str
    constraints: list[str] = Field(default_factory=list)
    examples: list[CodingProblemExampleModel] = Field(default_factory=list)
    starter_code: dict[str, str] = Field(default_factory=dict)
    expected_topics: list[str] = Field(default_factory=list)
    style_tags: list[str] = Field(default_factory=list)
    complexity_target: str | None = None
    edge_case_hints: list[str] = Field(default_factory=list)


class CodingInterviewEventModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    created_at: datetime = Field(default_factory=utcnow)
    transcript_excerpt: str | None = None
    code_excerpt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodingInterventionModel(BaseModel):
    question: str
    reason: str
    severity: str
    created_at: datetime = Field(default_factory=utcnow)
    prompt_key: str | None = None


class CodingConversationTurnModel(BaseModel):
    role: str
    content: str
    created_at: datetime = Field(default_factory=utcnow)
    kind: str = "message"
    source_event_type: str | None = None
    severity: str | None = None


class CodingInterviewEvaluationModel(BaseModel):
    communication: int
    problem_solving: int
    coding: int
    complexity_analysis: int
    debugging: int
    edge_cases: int
    overall_score: int
    hire_recommendation: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


class CodingInterviewRoundModel(BaseModel):
    enabled: bool = True
    target_company: str | None = None
    matched_company: str | None = None
    selection_strategy: str = "exact_company"
    interviewer_mode: str = "neutral"
    difficulty: str = "medium"
    problem: CodingProblemModel | None = None
    selection_rationale: str | None = None
    language: str = "typescript"
    editor_mode: str = "monaco"
    current_code: str = ""
    transcript: str = ""
    interviewer_prompt: str | None = None
    current_mode: str | None = None
    event_log: list[CodingInterviewEventModel] = Field(default_factory=list)
    conversation: list[CodingConversationTurnModel] = Field(default_factory=list)
    interventions: list[CodingInterventionModel] = Field(default_factory=list)
    cooldown_seconds: int = 40
    last_intervention_at: datetime | None = None
    latest_reason: str | None = None
    evaluation: CodingInterviewEvaluationModel | None = None
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


class InterviewRuntimeTurnModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    stage: Literal["behavioral", "technical", "coding", "completed"]
    role: Literal["candidate", "interviewer", "system"]
    agent_name: str | None = None
    kind: Literal[
        "question",
        "followup",
        "answer",
        "hint",
        "model_answer",
        "clarification",
        "coding_reply",
        "intervention",
        "transition",
    ]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class InterviewHandoffTraceModel(BaseModel):
    from_agent: str
    to_agent: str
    stage: Literal["behavioral", "technical", "coding", "completed"]
    reason: str
    created_at: datetime = Field(default_factory=utcnow)


class InterviewDecisionTraceModel(BaseModel):
    active_agent: str
    decision_type: str
    summary: str
    stage: Literal["behavioral", "technical", "coding", "completed"]
    created_at: datetime = Field(default_factory=utcnow)


class InterviewSupportEntryModel(BaseModel):
    mode: Literal["hint", "model_answer"]
    stage: Literal["behavioral", "technical", "coding"]
    question_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=utcnow)


class InterviewBlueprintModel(BaseModel):
    role_title: str
    behavioral_goal: str
    technical_goal: str
    behavioral_target_questions: int
    technical_target_questions: int
    target_company: str | None = None
    focus_areas: list[str] = Field(default_factory=list)


class InterviewEvaluationModel(BaseModel):
    behavioral_score: int
    technical_score: int
    coding_score: int
    communication_score: int
    overall_score: int
    job_match_score: int | None = None
    behavioral_feedback: str
    technical_feedback: str
    coding_feedback: str
    communication_feedback: str
    job_match_feedback: str | None = None
    summary: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    hire_recommendation: str
    recommendation: str


class InterviewReportModel(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    behavioral_feedback: str
    technical_feedback: str
    communication_feedback: str
    job_match_score: int | None = None
    job_match_feedback: str | None = None
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    recommendation: str
    question_feedback: list[InterviewQuestionFeedbackModel] = Field(default_factory=list)
    coding_feedback: str = ""
    coding_evaluation: CodingInterviewEvaluationModel | None = None
    hire_recommendation: str = ""


class InterviewSessionModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID | None = None
    company_id: UUID | None = None
    company_name: str | None = None
    company_context: str | None = None
    resume_link: str | None = None
    resume_text: str | None = None
    proceed_without_resume: bool = False
    job_description_link: str | None = None
    job_description_text: str | None = None
    proceed_without_job_description: bool = False
    transcript: str | None = None
    interview_length: str | None = None
    role_title: str | None = None
    target_company: str | None = None
    voice_enabled: bool = False
    preferred_language: str = "typescript"
    coding_difficulty: str = "medium"
    interviewer_mode: str = "neutral"
    current_stage: Literal["behavioral", "technical", "coding", "completed"] = "behavioral"
    active_agent: str | None = None
    interview_blueprint: InterviewBlueprintModel | None = None
    current_prompt: InterviewRuntimeTurnModel | None = None
    turn_log: list[InterviewRuntimeTurnModel] = Field(default_factory=list)
    handoff_history: list[InterviewHandoffTraceModel] = Field(default_factory=list)
    decision_trace: list[InterviewDecisionTraceModel] = Field(default_factory=list)
    support_history: list[InterviewSupportEntryModel] = Field(default_factory=list)
    questions: list[InterviewQuestionModel] = Field(default_factory=list)
    answers: list[InterviewAnswerModel] = Field(default_factory=list)
    current_question_index: int = 0
    coding_round: CodingInterviewRoundModel | None = None
    evaluation: InterviewEvaluationModel | None = None
    score: int | None = None
    report: InterviewReportModel | None = None
    is_completed: bool = False
    practice_duration_seconds: int | None = None
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
    "user_id": "TEXT",
    "company_id": "TEXT",
    "company_name": "TEXT",
    "company_context": "TEXT",
    "interview_length": "TEXT",
    "role_title": "TEXT",
    "target_company": "TEXT",
    "voice_enabled": "INTEGER NOT NULL DEFAULT 0",
    "preferred_language": "TEXT NOT NULL DEFAULT 'typescript'",
    "coding_difficulty": "TEXT NOT NULL DEFAULT 'medium'",
    "interviewer_mode": "TEXT NOT NULL DEFAULT 'neutral'",
    "current_stage": "TEXT NOT NULL DEFAULT 'behavioral'",
    "active_agent": "TEXT",
    "interview_blueprint_json": "TEXT",
    "current_prompt_json": "TEXT",
    "turn_log_json": "TEXT NOT NULL DEFAULT '[]'",
    "handoff_history_json": "TEXT NOT NULL DEFAULT '[]'",
    "decision_trace_json": "TEXT NOT NULL DEFAULT '[]'",
    "support_history_json": "TEXT NOT NULL DEFAULT '[]'",
    "questions_json": "TEXT NOT NULL DEFAULT '[]'",
    "answers_json": "TEXT NOT NULL DEFAULT '[]'",
    "current_question_index": "INTEGER NOT NULL DEFAULT 0",
    "coding_round_json": "TEXT",
    "evaluation_json": "TEXT",
    "score": "INTEGER",
    "report_json": "TEXT",
    "practice_duration_seconds": "INTEGER NOT NULL DEFAULT 0",
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


def _serialize_coding_round(value: CodingInterviewRoundModel | None) -> str | None:
    if value is None:
        return None
    return _json_default(value.model_dump(mode="json"))


def _serialize_object(value: BaseModel | None) -> str | None:
    if value is None:
        return None
    return _json_default(value.model_dump(mode="json"))


def _serialize_model_list(value: Iterable[BaseModel]) -> str:
    return _json_default([item.model_dump(mode="json") for item in value])


def _row_to_model(row: aiosqlite.Row) -> InterviewSessionModel:
    created_at = _parse_datetime(row["created_at"]) or utcnow()
    updated_at = _parse_datetime(row["updated_at"]) or utcnow()

    return InterviewSessionModel(
        id=UUID(row["id"]),
        user_id=UUID(row["user_id"]) if row["user_id"] else None,
        company_id=UUID(row["company_id"]) if row["company_id"] else None,
        company_name=row["company_name"],
        company_context=row["company_context"],
        resume_link=row["resume_link"],
        resume_text=row["resume_text"],
        proceed_without_resume=bool(row["proceed_without_resume"]),
        job_description_link=row["job_description_link"],
        job_description_text=row["job_description_text"],
        proceed_without_job_description=bool(row["proceed_without_job_description"]),
        transcript=row["transcript"],
        interview_length=row["interview_length"],
        role_title=row["role_title"],
        target_company=row["target_company"],
        voice_enabled=bool(row["voice_enabled"]),
        preferred_language=row["preferred_language"] or "typescript",
        coding_difficulty=row["coding_difficulty"] or "medium",
        interviewer_mode=row["interviewer_mode"] or "neutral",
        current_stage=row["current_stage"] or "behavioral",
        active_agent=row["active_agent"],
        interview_blueprint=_load_json_object(row["interview_blueprint_json"], InterviewBlueprintModel),
        current_prompt=_load_json_object(row["current_prompt_json"], InterviewRuntimeTurnModel),
        turn_log=_load_json_list(row["turn_log_json"], InterviewRuntimeTurnModel),
        handoff_history=_load_json_list(row["handoff_history_json"], InterviewHandoffTraceModel),
        decision_trace=_load_json_list(row["decision_trace_json"], InterviewDecisionTraceModel),
        support_history=_load_json_list(row["support_history_json"], InterviewSupportEntryModel),
        questions=_load_json_list(row["questions_json"], InterviewQuestionModel),
        answers=_load_json_list(row["answers_json"], InterviewAnswerModel),
        current_question_index=int(row["current_question_index"] or 0),
        coding_round=_load_json_object(row["coding_round_json"], CodingInterviewRoundModel),
        evaluation=_load_json_object(row["evaluation_json"], InterviewEvaluationModel),
        score=row["score"],
        report=_load_json_object(row["report_json"], InterviewReportModel),
        is_completed=bool(row["is_completed"]),
        practice_duration_seconds=int(row["practice_duration_seconds"] or 0),
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

    async def _init_problem_bank(self, conn: aiosqlite.Connection) -> None:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS CodingProblems (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                title TEXT NOT NULL,
                style_tags_json TEXT NOT NULL DEFAULT '[]',
                problem_json TEXT NOT NULL
            )
            """
        )

        for raw_problem in DEFAULT_CODING_PROBLEMS:
            problem = CodingProblemModel.model_validate(raw_problem)
            await conn.execute(
                """
                INSERT INTO CodingProblems (
                    id,
                    company,
                    difficulty,
                    title,
                    style_tags_json,
                    problem_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    company = excluded.company,
                    difficulty = excluded.difficulty,
                    title = excluded.title,
                    style_tags_json = excluded.style_tags_json,
                    problem_json = excluded.problem_json
                """,
                (
                    problem.id,
                    problem.company,
                    problem.difficulty,
                    problem.title,
                    _json_default(problem.style_tags),
                    _json_default(problem.model_dump(mode="json")),
                ),
            )

    async def init_db(self) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS InterviewSessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    company_id TEXT,
                    company_name TEXT,
                    company_context TEXT,
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
                    target_company TEXT,
                    voice_enabled INTEGER NOT NULL DEFAULT 0,
                    preferred_language TEXT NOT NULL DEFAULT 'typescript',
                    coding_difficulty TEXT NOT NULL DEFAULT 'medium',
                    interviewer_mode TEXT NOT NULL DEFAULT 'neutral',
                    current_stage TEXT NOT NULL DEFAULT 'behavioral',
                    active_agent TEXT,
                    interview_blueprint_json TEXT,
                    current_prompt_json TEXT,
                    turn_log_json TEXT NOT NULL DEFAULT '[]',
                    handoff_history_json TEXT NOT NULL DEFAULT '[]',
                    decision_trace_json TEXT NOT NULL DEFAULT '[]',
                    support_history_json TEXT NOT NULL DEFAULT '[]',
                    questions_json TEXT NOT NULL DEFAULT '[]',
                    answers_json TEXT NOT NULL DEFAULT '[]',
                    current_question_index INTEGER NOT NULL DEFAULT 0,
                    coding_round_json TEXT,
                    evaluation_json TEXT,
                    score INTEGER,
                    report_json TEXT,
                    practice_duration_seconds INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT
                )
                """
            )
            await self._ensure_optional_columns(conn)
            await self._init_problem_bank(conn)
            await conn.commit()

    async def add_interview_session(self, record: InterviewSessionModel) -> InterviewSessionModel:
        now = utcnow()
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO InterviewSessions (
                    id,
                    user_id,
                    company_id,
                    company_name,
                    company_context,
                    resume_link,
                    resume_text,
                    proceed_without_resume,
                    job_description_link,
                    job_description_text,
                    proceed_without_job_description,
                    transcript,
                    interview_length,
                    role_title,
                    target_company,
                    voice_enabled,
                    preferred_language,
                    coding_difficulty,
                    interviewer_mode,
                    current_stage,
                    active_agent,
                    interview_blueprint_json,
                    current_prompt_json,
                    turn_log_json,
                    handoff_history_json,
                    decision_trace_json,
                    support_history_json,
                    questions_json,
                    answers_json,
                    current_question_index,
                    coding_round_json,
                    evaluation_json,
                    score,
                    report_json,
                    practice_duration_seconds,
                    is_completed,
                    created_at,
                    updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.id),
                    str(record.user_id) if record.user_id else None,
                    str(record.company_id) if record.company_id else None,
                    record.company_name,
                    record.company_context,
                    record.resume_link,
                    record.resume_text,
                    int(record.proceed_without_resume),
                    record.job_description_link,
                    record.job_description_text,
                    int(record.proceed_without_job_description),
                    record.transcript,
                    record.interview_length,
                    record.role_title,
                    record.target_company,
                    int(record.voice_enabled),
                    record.preferred_language,
                    record.coding_difficulty,
                    record.interviewer_mode,
                    record.current_stage,
                    record.active_agent,
                    _serialize_object(record.interview_blueprint),
                    _serialize_object(record.current_prompt),
                    _serialize_model_list(record.turn_log),
                    _serialize_model_list(record.handoff_history),
                    _serialize_model_list(record.decision_trace),
                    _serialize_model_list(record.support_history),
                    _serialize_questions(record.questions),
                    _serialize_answers(record.answers),
                    record.current_question_index,
                    _serialize_coding_round(record.coding_round),
                    _serialize_object(record.evaluation),
                    record.score,
                    _serialize_report(record.report),
                    record.practice_duration_seconds or 0,
                    int(record.is_completed),
                    (record.created_at or now).isoformat(),
                    (record.updated_at or now).isoformat(),
                    record.completed_at.isoformat() if record.completed_at else None,
                ),
            )
            await conn.commit()

        existing = await self.get_interview_session(record.id, record.user_id)
        if existing is None:
            raise RuntimeError("Failed to insert interview session")
        return existing

    async def list_coding_problems(self) -> list[CodingProblemModel]:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT problem_json FROM CodingProblems ORDER BY company, title")
            rows = await cursor.fetchall()

        problems: list[CodingProblemModel] = []
        for row in rows:
            problem = _load_json_object(row["problem_json"], CodingProblemModel)
            if isinstance(problem, CodingProblemModel):
                problems.append(problem)
        return problems

    async def get_coding_problem(self, problem_id: str) -> CodingProblemModel | None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT problem_json FROM CodingProblems WHERE id = ?", (problem_id,))
            row = await cursor.fetchone()

        if not row:
            return None
        problem = _load_json_object(row["problem_json"], CodingProblemModel)
        return problem if isinstance(problem, CodingProblemModel) else None

    async def get_all_interview_sessions(self, user_id: UUID | None = None) -> list[InterviewSessionModel]:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            if user_id is None:
                cursor = await conn.execute("SELECT * FROM InterviewSessions ORDER BY created_at DESC")
            else:
                cursor = await conn.execute(
                    "SELECT * FROM InterviewSessions WHERE user_id = ? ORDER BY created_at DESC",
                    (str(user_id),),
                )
            rows = await cursor.fetchall()
            return [_row_to_model(r) for r in rows]

    async def get_interview_session(
        self,
        session_id: UUID,
        user_id: UUID | None = None,
    ) -> InterviewSessionModel | None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            if user_id is None:
                cursor = await conn.execute("SELECT * FROM InterviewSessions WHERE id = ?", (str(session_id),))
            else:
                cursor = await conn.execute(
                    "SELECT * FROM InterviewSessions WHERE id = ? AND user_id = ?",
                    (str(session_id), str(user_id)),
                )
            row = await cursor.fetchone()
            return _row_to_model(row) if row else None

    async def update_interview_session(
        self,
        record: InterviewSessionModel,
        user_id: UUID | None = None,
    ) -> InterviewSessionModel | None:
        existing = await self.get_interview_session(record.id, user_id)
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
            user_id=pick("user_id"),
            company_id=pick("company_id"),
            company_name=pick("company_name"),
            company_context=pick("company_context"),
            resume_link=pick("resume_link"),
            resume_text=pick("resume_text"),
            proceed_without_resume=pick("proceed_without_resume"),
            job_description_link=pick("job_description_link"),
            job_description_text=pick("job_description_text"),
            proceed_without_job_description=pick("proceed_without_job_description"),
            transcript=transcript,
            interview_length=pick("interview_length"),
            role_title=pick("role_title"),
            target_company=pick("target_company"),
            voice_enabled=pick("voice_enabled"),
            preferred_language=pick("preferred_language"),
            coding_difficulty=pick("coding_difficulty"),
            interviewer_mode=pick("interviewer_mode"),
            current_stage=pick("current_stage"),
            active_agent=pick("active_agent"),
            interview_blueprint=pick("interview_blueprint"),
            current_prompt=pick("current_prompt"),
            turn_log=pick("turn_log"),
            handoff_history=pick("handoff_history"),
            decision_trace=pick("decision_trace"),
            support_history=pick("support_history"),
            questions=pick("questions"),
            answers=pick("answers"),
            current_question_index=pick("current_question_index"),
            coding_round=pick("coding_round"),
            evaluation=pick("evaluation"),
            score=pick("score"),
            report=pick("report"),
            is_completed=pick("is_completed"),
            practice_duration_seconds=pick("practice_duration_seconds"),
            created_at=existing.created_at,
            updated_at=utcnow(),
            completed_at=pick("completed_at"),
        )

        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                UPDATE InterviewSessions
                SET user_id = ?,
                    company_id = ?,
                    company_name = ?,
                    company_context = ?,
                    resume_link = ?,
                    resume_text = ?,
                    proceed_without_resume = ?,
                    job_description_link = ?,
                    job_description_text = ?,
                    proceed_without_job_description = ?,
                    transcript = ?,
                    interview_length = ?,
                    role_title = ?,
                    target_company = ?,
                    voice_enabled = ?,
                    preferred_language = ?,
                    coding_difficulty = ?,
                    interviewer_mode = ?,
                    current_stage = ?,
                    active_agent = ?,
                    interview_blueprint_json = ?,
                    current_prompt_json = ?,
                    turn_log_json = ?,
                    handoff_history_json = ?,
                    decision_trace_json = ?,
                    support_history_json = ?,
                    questions_json = ?,
                    answers_json = ?,
                    current_question_index = ?,
                    coding_round_json = ?,
                    evaluation_json = ?,
                    score = ?,
                    report_json = ?,
                    practice_duration_seconds = ?,
                    is_completed = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    str(updated_record.user_id) if updated_record.user_id else None,
                    str(updated_record.company_id) if updated_record.company_id else None,
                    updated_record.company_name,
                    updated_record.company_context,
                    updated_record.resume_link,
                    updated_record.resume_text,
                    int(updated_record.proceed_without_resume),
                    updated_record.job_description_link,
                    updated_record.job_description_text,
                    int(updated_record.proceed_without_job_description),
                    updated_record.transcript,
                    updated_record.interview_length,
                    updated_record.role_title,
                    updated_record.target_company,
                    int(updated_record.voice_enabled),
                    updated_record.preferred_language,
                    updated_record.coding_difficulty,
                    updated_record.interviewer_mode,
                    updated_record.current_stage,
                    updated_record.active_agent,
                    _serialize_object(updated_record.interview_blueprint),
                    _serialize_object(updated_record.current_prompt),
                    _serialize_model_list(updated_record.turn_log),
                    _serialize_model_list(updated_record.handoff_history),
                    _serialize_model_list(updated_record.decision_trace),
                    _serialize_model_list(updated_record.support_history),
                    _serialize_questions(updated_record.questions),
                    _serialize_answers(updated_record.answers),
                    updated_record.current_question_index,
                    _serialize_coding_round(updated_record.coding_round),
                    _serialize_object(updated_record.evaluation),
                    updated_record.score,
                    _serialize_report(updated_record.report),
                    updated_record.practice_duration_seconds or 0,
                    int(updated_record.is_completed),
                    updated_record.updated_at.isoformat(),
                    updated_record.completed_at.isoformat() if updated_record.completed_at else None,
                    str(updated_record.id),
                ),
            )
            await conn.commit()

        return await self.get_interview_session(record.id, user_id or existing.user_id)

    async def complete_interview_session(
        self,
        session_id: UUID,
        user_id: UUID | None = None,
    ) -> InterviewSessionModel | None:
        current = await self.get_interview_session(session_id, user_id)
        if current is None:
            return None

        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                UPDATE InterviewSessions
                SET is_completed = 1,
                    current_stage = 'completed',
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (utcnow().isoformat(), utcnow().isoformat(), str(session_id)),
            )
            await conn.commit()

        return await self.get_interview_session(session_id, user_id or current.user_id)

    async def ensure_session(self, session_id: UUID, user_id: UUID | None = None) -> InterviewSessionModel:
        existing = await self.get_interview_session(session_id, user_id)
        if existing is not None:
            return existing
        return await self.add_interview_session(InterviewSessionModel(id=session_id, user_id=user_id))

    async def append_turn(
        self,
        session_id: UUID,
        payload: SessionTurnUpdate,
        user_id: UUID | None = None,
    ) -> InterviewSessionModel:
        session = await self.ensure_session(session_id, user_id)
        updated = await self.update_interview_session(
            InterviewSessionModel(
                id=session.id,
                user_id=session.user_id,
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

    async def increment_practice_duration(
        self,
        session_id: UUID,
        seconds: int,
        user_id: UUID | None = None,
    ) -> InterviewSessionModel | None:
        current = await self.get_interview_session(session_id, user_id)
        if current is None:
            return None

        async with aiosqlite.connect(DATABASE_PATH) as conn:
            if user_id is None:
                await conn.execute(
                    """
                    UPDATE InterviewSessions
                    SET practice_duration_seconds = COALESCE(practice_duration_seconds, 0) + ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (seconds, utcnow().isoformat(), str(session_id)),
                )
            else:
                await conn.execute(
                    """
                    UPDATE InterviewSessions
                    SET practice_duration_seconds = COALESCE(practice_duration_seconds, 0) + ?,
                        updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (seconds, utcnow().isoformat(), str(session_id), str(user_id)),
                )
            await conn.commit()

        return await self.get_interview_session(session_id, user_id or current.user_id)

    async def delete_interview_session(self, session_id: UUID, user_id: UUID | None = None) -> bool:
        existing = await self.get_interview_session(session_id, user_id)
        if existing is None:
            return False

        async with aiosqlite.connect(DATABASE_PATH) as conn:
            if user_id is None:
                await conn.execute("DELETE FROM InterviewSessions WHERE id = ?", (str(session_id),))
            else:
                await conn.execute(
                    "DELETE FROM InterviewSessions WHERE id = ? AND user_id = ?",
                    (str(session_id), str(user_id)),
                )
            await conn.commit()

        return True
