import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import tempfile
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path
from typing import Any
from uuid import UUID

import fastapi
import fastapi.concurrency
import fastapi.responses
import fastapi.staticfiles
import httpx
import opentelemetry.instrumentation.fastapi as otel_fastapi
import telemetry
from pydantic import BaseModel, Field

from auth_store import AuthRepository, UserModel
from company_store import CompanyKnowledgeSourceModel, CompanyModel, CompanyRepository
from coding_interview_engine import (
    CodingInterventionDecisionModel,
    InterviewInterventionEngine,
    apply_intervention,
    build_ai_interviewer_prompt,
    choose_coding_problem,
    looks_like_clarification_request,
    looks_like_reasoning_update,
)
from interview_data_store import (
    CodingConversationTurnModel,
    CodingInterviewEvaluationModel,
    CodingInterviewEventModel,
    CodingInterviewRoundModel,
    InterviewAnswerModel,
    InterviewQuestionFeedbackModel,
    InterviewQuestionModel,
    InterviewReportModel,
    InterviewSessionModel,
    InterviewSessionRepository,
    SessionTurnUpdate,
    utcnow,
)
from services.rag_service import delete_company_knowledge, index_company_document, retrieve_company_context


repo = InterviewSessionRepository()
auth_repo = AuthRepository()
company_repo = CompanyRepository()
intervention_engine = InterviewInterventionEngine()


@contextlib.asynccontextmanager
async def lifespan(app):
    telemetry.configure_opentelemetry()
    await auth_repo.init_db()
    await auth_repo.delete_expired_tokens()
    await repo.init_db()
    await company_repo.init_db()
    yield


app = fastapi.FastAPI(lifespan=lifespan)
otel_fastapi.FastAPIInstrumentor.instrument_app(app, exclude_spans=["send"])


logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

INTERVIEW_LENGTH_OPTIONS: dict[str, dict[str, int]] = {
    "short": {"behavioral": 2, "technical": 2},
    "medium": {"behavioral": 4, "technical": 4},
    "long": {"behavioral": 6, "technical": 6},
}
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html"}


def get_agent_base_url() -> str:
    return (
        os.getenv("INTERVIEW_PREP_AGENTS_URL")
        or os.getenv("AGENT_HTTPS")
        or os.getenv("AGENT_HTTP")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


def get_openai_base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")


def get_openai_api_key() -> str:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise fastapi.HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    return api_key


def get_realtime_model() -> str:
    return (os.getenv("OPENAI_REALTIME_MODEL") or "gpt-realtime").strip()


def get_realtime_transcription_model() -> str:
    return (os.getenv("OPENAI_REALTIME_TRANSCRIPTION_MODEL") or "gpt-realtime-whisper").strip()


class InterviewSessionRecordRequest(BaseModel):
    record: InterviewSessionModel


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)


class AuthResponse(BaseModel):
    token: str
    user: UserModel


class ParsedDocumentResponse(BaseModel):
    file_name: str
    extracted_text: str


class CompanyCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    website: str | None = None


class CompanyKnowledgeMetadata(BaseModel):
    role: str | None = None
    category: str | None = None
    url: str | None = None


class CompanyKnowledgeTextRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_type: str = Field(
        pattern="^(manual|official_page|job_description|engineering_blog|interview_guide)$"
    )
    metadata: CompanyKnowledgeMetadata = Field(default_factory=CompanyKnowledgeMetadata)


class CompanyKnowledgeUpdateRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_type: str = Field(
        pattern="^(manual|official_page|job_description|engineering_blog|interview_guide)$"
    )
    metadata: CompanyKnowledgeMetadata = Field(default_factory=CompanyKnowledgeMetadata)


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)

class InterviewCreateRequest(BaseModel):
    resume_text: str = Field(min_length=1)
    job_description_text: str = Field(min_length=1)
    interview_length: str = Field(pattern="^(short|medium|long)$")
    target_company: str | None = Field(default=None, max_length=80)
    company_id: str | None = None
    coding_difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    interviewer_mode: str = Field(default="neutral", pattern="^(warm|neutral|bar_raiser|silent)$")
    preferred_language: str = Field(default="typescript", pattern="^(typescript|javascript|python|java|csharp)$")


class InterviewAnswerRequest(BaseModel):
    answer_text: str = Field(min_length=1)


class PracticeDurationUpdateRequest(BaseModel):
    seconds: int = Field(ge=1, le=3600)


class InterviewFinishRequest(BaseModel):
    answer_text: str | None = None
    code: str | None = None
    language: str | None = Field(default=None, pattern="^(typescript|javascript|python|java|csharp)$")
    transcript_recent: str = ""


class InterviewHelpResponse(BaseModel):
    question_id: str
    content: str


class CompanyKnowledgeSourceResponse(BaseModel):
    id: str
    company_id: str
    title: str
    source_type: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class RagSearchResult(BaseModel):
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    distance: float | None = None


class InterviewHistoryItem(BaseModel):
    id: str
    role_title: str
    interview_length: str | None = None
    target_company: str | None = None
    company_id: str | None = None
    company_name: str | None = None
    question_count: int
    answered_count: int
    is_completed: bool
    score: int | None = None
    practice_duration_seconds: int | None = None
    created_at: str
    completed_at: str | None = None


class CodingEventRequest(BaseModel):
    event: CodingInterviewEventModel
    code: str = ""
    language: str | None = Field(default=None, pattern="^(typescript|javascript|python|java|csharp)$")
    transcript_append: str = ""


class CodingInterventionRequest(BaseModel):
    problem_id: str = Field(min_length=1)
    code: str = ""
    language: str = Field(pattern="^(typescript|javascript|python|java|csharp)$")
    transcript_recent: str = ""
    recent_events: list[CodingInterviewEventModel] = Field(default_factory=list)
    elapsed_time_seconds: int = Field(ge=0)


class CodingInterventionResponse(BaseModel):
    should_interrupt: bool
    reason: str | None = None
    question: str | None = None
    severity: str = "none"
    reply: str | None = None
    coding_round: CodingInterviewRoundModel | None = None


class CodingRealtimeSessionRequest(BaseModel):
    sdp: str = Field(min_length=1)
    voice: str | None = Field(default=None, max_length=40)


class CodingRealtimeSessionResponse(BaseModel):
    sdp: str
    model: str
    voice: str
    transcription_model: str


def _truncate(text: str, limit: int = 240) -> str:
    return text if len(text) <= limit else f"{text[:limit]}..."


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _to_sentence_case(text: str) -> str:
    cleaned = _normalize_whitespace(text).strip(" -")
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def _safe_excerpt(text: str, limit: int = 220) -> str:
    compact = _normalize_whitespace(text)
    return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}..."


def _normalize_email(email: str) -> str:
    return email.strip().lower()



def _source_to_response(source: CompanyKnowledgeSourceModel) -> CompanyKnowledgeSourceResponse:
    return CompanyKnowledgeSourceResponse(
        id=str(source.id),
        company_id=str(source.company_id),
        title=source.title,
        source_type=source.source_type,
        content=source.content,
        metadata=source.metadata_json,
        created_at=source.created_at.isoformat(),
    )


async def _require_company(company_id: str) -> CompanyModel:
    try:
        company_uuid = UUID(company_id)
    except ValueError as exc:
        raise fastapi.HTTPException(status_code=400, detail="Invalid company id") from exc

    company = await company_repo.get_company(company_uuid)
    if company is None:
        raise fastapi.HTTPException(status_code=404, detail="Company not found")
    return company


def _build_company_rag_query(*, job_description_text: str, role_title: str, question_prompt: str | None = None) -> str:
    parts = [role_title.strip(), job_description_text.strip()[:1800]]
    if question_prompt:
        parts.append(question_prompt.strip())
    return "\n\n".join(part for part in parts if part)


async def _retrieve_company_context_text(
    *,
    company_id: UUID | None,
    company_name: str | None,
    query: str,
    top_k: int = 5,
) -> str | None:
    if company_id is None or not query.strip():
        return None

    try:
        rows = await fastapi.concurrency.run_in_threadpool(
            retrieve_company_context,
            str(company_id),
            query,
            top_k,
        )
    except Exception:
        logger.exception("company rag retrieval failed for company_id=%s", company_id)
        return None

    if not rows:
        return None

    blocks: list[str] = []
    for index, row in enumerate(rows, start=1):
        metadata = row.get("metadata") or {}
        title = str(metadata.get("title") or f"Source {index}")
        source_type = str(metadata.get("source_type") or "knowledge")
        role = str(metadata.get("role") or "").strip()
        category = str(metadata.get("category") or "").strip()
        content = _normalize_whitespace(str(row.get("content") or ""))
        labels = ", ".join(part for part in [source_type, role, category] if part)
        header = f"{index}. {title}" if not labels else f"{index}. {title} ({labels})"
        blocks.append(f"{header}\n{content}")

    company_label = company_name or "the target company"
    return (
        f"Company-specific knowledge for {company_label}.\n"
        "Use it as supporting context when tailoring questions or answers, but stay grounded in the resume and job description.\n\n"
        + "\n\n".join(blocks)
    )


async def _reindex_company_knowledge(company: CompanyModel, sources: list[CompanyKnowledgeSourceModel]) -> None:
    await fastapi.concurrency.run_in_threadpool(delete_company_knowledge, str(company.id))

    for source in sources:
        await fastapi.concurrency.run_in_threadpool(
            index_company_document,
            str(company.id),
            company.name,
            source.title,
            source.content,
            source.source_type,
            {
                **source.metadata_json,
                "source_id": str(source.id),
                "created_at": source.created_at.isoformat(),
            },
        )


def _merge_knowledge_metadata(
    metadata: CompanyKnowledgeMetadata,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(fallback or {})
    if metadata.role:
        merged["role"] = metadata.role
    if metadata.category:
        merged["category"] = metadata.category
    if metadata.url:
        merged["url"] = metadata.url
    return merged


def _parse_metadata_form(metadata_json: str | None) -> CompanyKnowledgeMetadata:
    if not metadata_json:
        return CompanyKnowledgeMetadata()
    try:
        payload = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise fastapi.HTTPException(status_code=400, detail="metadata_json must be valid JSON") from exc
    return CompanyKnowledgeMetadata.model_validate(payload if isinstance(payload, dict) else {})


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 200_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return (
        f"{iterations}$"
        f"{urlsafe_b64encode(salt).decode('ascii')}$"
        f"{urlsafe_b64encode(digest).decode('ascii')}"
    )


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        iterations_raw, salt_raw, digest_raw = password_hash.split("$", 2)
        iterations = int(iterations_raw)
        salt = urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = urlsafe_b64decode(digest_raw.encode("ascii"))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _issue_access_token() -> str:
    return secrets.token_urlsafe(48)


async def _get_current_user(authorization: str | None = fastapi.Header(default=None)) -> UserModel:
    if not authorization:
        raise fastapi.HTTPException(status_code=401, detail="Authentication required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise fastapi.HTTPException(status_code=401, detail="Invalid authentication scheme")

    user = await auth_repo.get_user_by_token(token.strip())
    if user is None:
        raise fastapi.HTTPException(status_code=401, detail="Invalid or expired session")
    return user


async def _get_bearer_token(authorization: str | None = fastapi.Header(default=None)) -> str:
    if not authorization:
        raise fastapi.HTTPException(status_code=401, detail="Authentication required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise fastapi.HTTPException(status_code=401, detail="Invalid authentication scheme")
    return token.strip()


def _extract_role_title(job_description_text: str) -> str:
    patterns = [
        r"(?im)^(?:job title|position|role)\s*[:\-]\s*(.+)$",
        r"(?im)^#+\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, job_description_text)
        if match:
            title = _to_sentence_case(match.group(1))
            if title:
                return title

    for line in job_description_text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue
        if stripped.startswith(("-", "*")):
            continue
        return _to_sentence_case(stripped)

    return "Target role"


def _agent_timeout_for_path(path: str) -> float:
    return {
        "/interview/plan": 120.0,
        "/interview/report": 120.0,
        "/interview/help": 45.0,
        "/coding/reply": 45.0,
        "/coding/evaluate": 90.0,
    }.get(path, 60.0)


def _build_realtime_session_config(*, voice: str) -> dict[str, Any]:
    return {
        "type": "realtime",
        "model": get_realtime_model(),
        "output_modalities": ["audio"],
        "instructions": (
            "You are the voice transport layer for a coding interview application. "
            "Continuously transcribe the candidate's speech. "
            "Do not proactively answer the candidate or ask questions on your own. "
            "The application will decide interviewer replies separately. "
            "When the application explicitly requests audio output, read the provided interviewer text naturally "
            "and keep the wording exact."
        ),
        "audio": {
            "input": {
                "turn_detection": {
                    "type": "server_vad",
                    "create_response": False,
                    "interrupt_response": False,
                    "silence_duration_ms": 900,
                    "prefix_padding_ms": 300,
                },
                "transcription": {
                    "model": get_realtime_transcription_model(),
                    "language": "en",
                },
            },
            "output": {
                "voice": voice,
            },
        },
    }


async def _create_realtime_call(*, sdp_offer: str, voice: str, current_user: UserModel) -> str:
    user_id_text = str(current_user.id)
    session_config = _build_realtime_session_config(voice=voice)
    files = {
        "sdp": (None, sdp_offer),
        "session": (None, json.dumps(session_config), "application/json"),
    }
    headers = {
        "Authorization": f"Bearer {get_openai_api_key()}",
        "OpenAI-Safety-Identifier": hashlib.sha256(user_id_text.encode("utf-8")).hexdigest(),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{get_openai_base_url()}/realtime/calls",
                files=files,
                headers=headers,
            )
            response.raise_for_status()
            sdp_answer = response.text
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or "Failed to initialize realtime voice session"
        raise fastapi.HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise fastapi.HTTPException(status_code=502, detail="Realtime voice session unavailable") from exc
    return sdp_answer


async def _post_agent_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = _agent_timeout_for_path(path)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{get_agent_base_url()}{path}",
                json=payload,
                headers={"x-trace-id": uuid.uuid4().hex[:12]},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or f"Agent request failed for {path}"
        raise fastapi.HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise fastapi.HTTPException(status_code=502, detail=f"Agent service unavailable for {path}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise fastapi.HTTPException(status_code=502, detail=f"Agent service returned invalid JSON for {path}") from exc
    if not isinstance(data, dict):
        raise fastapi.HTTPException(status_code=502, detail=f"Agent service returned an invalid payload for {path}")
    return data


def _coding_event_needs_reply(recent_events: list[CodingInterviewEventModel], transcript_recent: str) -> bool:
    if transcript_recent.strip():
        return any(
            event.type in {"candidate_spoke", "clarification_asked", "solution_explained", "candidate_pause"}
            for event in recent_events
        )
    return False


def _should_send_coding_reply(
    round_state: CodingInterviewRoundModel,
    recent_events: list[CodingInterviewEventModel],
    transcript_recent: str,
    decision: CodingInterventionDecisionModel | None = None,
) -> bool:
    if not _coding_event_needs_reply(recent_events, transcript_recent):
        return bool(decision and decision.should_interrupt and decision.question)

    if decision and decision.should_interrupt and decision.question:
        return True

    latest_event = recent_events[-1] if recent_events else None
    latest_text = _normalize_whitespace(transcript_recent)
    if not latest_event or not latest_text:
        return False

    if latest_event.type == "clarification_asked" or looks_like_clarification_request(latest_text):
        return True

    if latest_event.type in {"candidate_pause", "solution_explained"}:
        return True

    # Let the candidate continue coding after ordinary reasoning updates instead of
    # turning every spoken thought into a new interviewer question.
    if latest_event.type == "candidate_spoke":
        if _candidate_answered_latest_interviewer_turn(round_state, transcript_recent):
            return False
        return False

    return False


def _latest_coding_interviewer_turn(round_state: CodingInterviewRoundModel) -> CodingConversationTurnModel | None:
    for turn in reversed(round_state.conversation):
        if turn.role == "interviewer" and turn.content.strip():
            return turn
    return None


def _conversation_has_recent_duplicate(round_state: CodingInterviewRoundModel, reply: str) -> bool:
    cleaned = _normalize_whitespace(reply)
    if not cleaned:
        return False
    recent_interviewer_lines = [
        _normalize_whitespace(turn.content)
        for turn in round_state.conversation[-4:]
        if turn.role == "interviewer"
    ]
    return cleaned in recent_interviewer_lines


def _candidate_answered_latest_interviewer_turn(
    round_state: CodingInterviewRoundModel,
    transcript_recent: str,
) -> bool:
    latest_interviewer = _latest_coding_interviewer_turn(round_state)
    if latest_interviewer is None or not transcript_recent.strip():
        return False

    lowered_question = _normalize_whitespace(latest_interviewer.content).lower()
    lowered_answer = _normalize_whitespace(transcript_recent).lower()

    if looks_like_clarification_request(lowered_answer):
        return False

    if "time and space complexity" in lowered_question:
        return any(
            token in lowered_answer
            for token in ("time complexity", "space complexity", "big o", "o(", "linear", "constant", "quadratic")
        )
    if "edge case" in lowered_question:
        return any(token in lowered_answer for token in ("edge", "empty", "null", "zero", "duplicate", "negative"))
    if "trade-off" in lowered_question or "tradeoff" in lowered_question:
        return any(token in lowered_answer for token in ("tradeoff", "trade-off", "because", "memory", "space", "time"))
    if "what approach are you leaning toward" in lowered_question:
        return looks_like_reasoning_update(lowered_answer)
    if "talk me through" in lowered_question or "what is blocking you" in lowered_question:
        return looks_like_reasoning_update(lowered_answer)
    return False


def _build_problem_clarification_reply(round_state: CodingInterviewRoundModel) -> str:
    problem = round_state.problem
    if problem is None:
        return "Restate the input, the output you need to produce, and the main constraints before you pick an approach."

    example = problem.examples[0] if problem.examples else None
    example_text = (
        f" For example, {example.input} should produce {example.output}."
        if example
        else ""
    )
    constraints = ", ".join(problem.constraints[:2]).strip()
    constraints_text = f" Keep in mind: {constraints}." if constraints else ""
    return _normalize_whitespace(
        f"The task is to {problem.prompt}.{example_text}{constraints_text}"
    )


async def _generate_coding_interviewer_reply(
    *,
    round_state: CodingInterviewRoundModel,
    recent_events: list[CodingInterviewEventModel],
    transcript_recent: str,
    code: str,
    decision: CodingInterventionDecisionModel | None = None,
) -> str | None:
    if not _should_send_coding_reply(round_state, recent_events, transcript_recent, decision):
        return decision.question if decision and decision.should_interrupt else None

    if looks_like_clarification_request(transcript_recent):
        return _build_problem_clarification_reply(round_state)

    if not round_state.problem:
        raise fastapi.HTTPException(status_code=500, detail="Coding round is missing its problem definition")

    payload = await _post_agent_json(
        "/coding/reply",
        {
            "interviewer_prompt": round_state.interviewer_prompt or "",
            "interviewer_mode": round_state.interviewer_mode,
            "problem_title": round_state.problem.title,
            "problem_prompt": round_state.problem.prompt,
            "problem_constraints": round_state.problem.constraints,
            "problem_examples": [example.model_dump(mode="json") for example in round_state.problem.examples[:3]],
            "edge_case_hints": round_state.problem.edge_case_hints,
            "complexity_target": round_state.problem.complexity_target,
            "recent_event_types": [event.type for event in recent_events],
            "transcript_recent": transcript_recent.strip(),
            "current_code": _safe_excerpt(code[-1600:], 1600),
            "conversation": [turn.model_dump(mode="json") for turn in round_state.conversation[-8:]],
            "forced_followup": decision.question if decision and decision.should_interrupt else None,
        },
    )

    reply = _normalize_whitespace(str(payload.get("reply") or ""))
    if not reply:
        raise fastapi.HTTPException(status_code=502, detail="Coding interviewer returned an empty reply")
    if _conversation_has_recent_duplicate(round_state, reply):
        raise fastapi.HTTPException(status_code=502, detail="Coding interviewer returned a duplicate reply")
    return reply


async def _generate_ai_questions(
    resume_text: str,
    job_description_text: str,
    interview_length: str,
    *,
    company_name: str | None = None,
    company_context: str | None = None,
) -> tuple[str, list[InterviewQuestionModel]]:
    counts = INTERVIEW_LENGTH_OPTIONS[interview_length]
    payload = await _post_agent_json(
        "/interview/plan",
        {
            "resume_text": resume_text,
            "job_description_text": job_description_text,
            "interview_length": interview_length,
            "behavioral_count": counts["behavioral"],
            "technical_count": counts["technical"],
            "company_name": company_name,
            "company_context": company_context,
        },
    )

    role_title = _to_sentence_case(str(payload.get("role_title") or "")) or _extract_role_title(job_description_text)
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        raise fastapi.HTTPException(status_code=502, detail="Interview planner returned an invalid questions payload")

    questions: list[InterviewQuestionModel] = []
    for index, raw_question in enumerate(raw_questions, start=1):
        if not isinstance(raw_question, dict):
            continue
        prompt = _normalize_whitespace(str(raw_question.get("prompt") or ""))
        category = str(raw_question.get("category") or "").strip().lower()
        if not prompt or category not in {"behavioral", "technical"}:
            continue
        questions.append(
            InterviewQuestionModel(
                id=str(raw_question.get("id") or f"{category}-{index}"),
                order=index,
                category=category,
                prompt=prompt,
            )
        )

    expected_count = counts["behavioral"] + counts["technical"]
    if len(questions) != expected_count:
        raise fastapi.HTTPException(
            status_code=502,
            detail=f"Interview planner returned {len(questions)} questions instead of {expected_count}",
        )

    return role_title, questions


async def _build_coding_round(
    *,
    target_company: str | None,
    difficulty: str,
    interviewer_mode: str,
    preferred_language: str,
    role_title: str,
    job_description_text: str,
) -> CodingInterviewRoundModel | None:
    problems = await repo.list_coding_problems()
    if not problems:
        return None

    selection = choose_coding_problem(
        problems=problems,
        target_company=target_company,
        desired_difficulty=difficulty,
        role_title=role_title,
        job_description_text=job_description_text,
    )
    starter_code = selection.problem.starter_code.get(preferred_language) or next(
        iter(selection.problem.starter_code.values()),
        "",
    )

    return CodingInterviewRoundModel(
        target_company=(target_company or "").strip() or None,
        matched_company=selection.matched_company,
        selection_strategy=selection.selection_strategy,
        interviewer_mode=interviewer_mode,
        difficulty=difficulty,
        problem=selection.problem,
        language=preferred_language,
        editor_mode="plain" if difficulty == "hard" else "monaco",
        current_code=starter_code,
        interviewer_prompt=build_ai_interviewer_prompt(interviewer_mode, selection.problem),
        conversation=[
            CodingConversationTurnModel(
                role="interviewer",
                content=(
                    "Let's work through this problem together. Talk me through your approach as you go, "
                    "and ask if you want any clarification on the prompt."
                ),
                kind="opening",
            )
        ],
    )


async def _generate_ai_report(
    session: InterviewSessionModel,
    answers: list[InterviewAnswerModel],
    *,
    company_context: str | None = None,
) -> tuple[int, InterviewReportModel]:
    payload = await _post_agent_json(
        "/interview/report",
        {
            "resume_text": session.resume_text or "",
            "job_description_text": session.job_description_text or "",
            "interview_length": session.interview_length or "medium",
            "role_title": session.role_title or _extract_role_title(session.job_description_text or ""),
            "questions": [question.model_dump(mode="json") for question in session.questions],
            "answers": [answer.model_dump(mode="json") for answer in answers],
            "company_name": session.company_name or session.target_company,
            "company_context": company_context,
            "coding_feedback_input": (
                session.coding_round.evaluation.summary
                if session.coding_round and session.coding_round.evaluation
                else None
            ),
            "coding_hire_recommendation": (
                session.coding_round.evaluation.hire_recommendation
                if session.coding_round and session.coding_round.evaluation
                else None
            ),
        },
    )

    try:
        raw_feedback = payload.get("question_feedback", [])
        question_feedback = [
            InterviewQuestionFeedbackModel.model_validate(item)
            for item in raw_feedback
            if isinstance(item, dict)
        ]
        report = InterviewReportModel(
            summary=str(payload.get("summary") or "").strip(),
            strengths=[str(item).strip() for item in payload.get("strengths", []) if str(item).strip()],
            improvements=[str(item).strip() for item in payload.get("improvements", []) if str(item).strip()],
            behavioral_feedback=str(payload.get("behavioral_feedback") or "").strip(),
            technical_feedback=str(payload.get("technical_feedback") or "").strip(),
            communication_feedback=str(payload.get("communication_feedback") or "").strip(),
            recommendation=str(payload.get("recommendation") or "").strip(),
            question_feedback=question_feedback,
            coding_feedback=str(payload.get("coding_feedback") or "").strip(),
            coding_evaluation=session.coding_round.evaluation if session.coding_round else None,
            hire_recommendation=str(payload.get("hire_recommendation") or "").strip(),
        )
        score = int(payload.get("score"))
    except Exception as exc:
        raise fastapi.HTTPException(status_code=502, detail="Interview report agent returned an invalid payload") from exc

    if not report.summary or not report.recommendation:
        raise fastapi.HTTPException(status_code=502, detail="Interview report agent returned an incomplete report")

    return max(1, min(score, 100)), report


async def _generate_ai_help(
    help_kind: str,
    session: InterviewSessionModel,
    question: InterviewQuestionModel,
    *,
    company_context: str | None = None,
) -> str:
    payload = await _post_agent_json(
        "/interview/help",
        {
            "help_kind": help_kind,
            "role_title": session.role_title or _extract_role_title(session.job_description_text or ""),
            "question": question.model_dump(mode="json"),
            "resume_text": session.resume_text or "",
            "job_description_text": session.job_description_text or "",
            "company_name": session.company_name or session.target_company,
            "company_context": company_context,
        },
    )

    content = _normalize_whitespace(str(payload.get("content") or ""))
    if not content:
        raise fastapi.HTTPException(status_code=502, detail="Interview help agent returned empty content")
    return content


async def _generate_ai_coding_evaluation(
    round_state: CodingInterviewRoundModel,
) -> CodingInterviewEvaluationModel:
    if round_state.problem is None:
        raise fastapi.HTTPException(status_code=500, detail="Coding round is missing its problem definition")

    payload = await _post_agent_json(
        "/coding/evaluate",
        {
            "problem_title": round_state.problem.title,
            "problem_prompt": round_state.problem.prompt,
            "difficulty": round_state.difficulty,
            "language": round_state.language,
            "complexity_target": round_state.problem.complexity_target,
            "current_code": round_state.current_code,
            "transcript": round_state.transcript,
            "conversation": [turn.model_dump(mode="json") for turn in round_state.conversation],
            "event_log": [event.model_dump(mode="json") for event in round_state.event_log],
        },
    )

    try:
        return CodingInterviewEvaluationModel.model_validate(payload)
    except Exception as exc:
        raise fastapi.HTTPException(status_code=502, detail="Coding evaluation agent returned an invalid payload") from exc


def _session_transcript_entry(question: InterviewQuestionModel, answer_text: str) -> str:
    return (
        f"Interviewer ({question.category.title()} Q{question.order}): {question.prompt.strip()}\n"
        f"Candidate: {answer_text.strip()}"
    )


def _history_item_from_session(session: InterviewSessionModel) -> InterviewHistoryItem:
    return InterviewHistoryItem(
        id=str(session.id),
        role_title=session.role_title or _extract_role_title(session.job_description_text or "") or "Interview",
        interview_length=session.interview_length,
        target_company=session.target_company,
        company_id=str(session.company_id) if session.company_id else None,
        company_name=session.company_name,
        question_count=len(session.questions),
        answered_count=len(session.answers),
        is_completed=session.is_completed,
        score=session.score,
        practice_duration_seconds=session.practice_duration_seconds,
        created_at=session.created_at.isoformat(),
        completed_at=session.completed_at.isoformat() if session.completed_at else None,
    )


def _append_coding_round_state(
    round_state: CodingInterviewRoundModel,
    *,
    event: CodingInterviewEventModel | None = None,
    code: str | None = None,
    language: str | None = None,
    transcript_append: str = "",
) -> CodingInterviewRoundModel:
    transcript_bits = [round_state.transcript.strip()] if round_state.transcript.strip() else []
    if transcript_append.strip():
        transcript_bits.append(transcript_append.strip())
    elif event and event.transcript_excerpt:
        transcript_bits.append(event.transcript_excerpt.strip())

    next_events = round_state.event_log
    if event is not None:
        next_events = [*round_state.event_log, event]

    return round_state.model_copy(
        update={
            "current_code": code if code is not None else round_state.current_code,
            "language": language or round_state.language,
            "transcript": "\n".join(bit for bit in transcript_bits if bit).strip(),
            "event_log": next_events,
        }
    )


def _append_coding_conversation_turn(
    round_state: CodingInterviewRoundModel,
    *,
    role: str,
    content: str,
    kind: str = "message",
    source_event_type: str | None = None,
    severity: str | None = None,
) -> CodingInterviewRoundModel:
    cleaned = _normalize_whitespace(content)
    if not cleaned:
        return round_state

    existing = round_state.conversation[-1] if round_state.conversation else None
    if existing and existing.role == role and _normalize_whitespace(existing.content) == cleaned:
        return round_state

    return round_state.model_copy(
        update={
            "conversation": [
                *round_state.conversation,
                CodingConversationTurnModel(
                    role=role,
                    content=cleaned,
                    kind=kind,
                    source_event_type=source_event_type,
                    severity=severity,
                ),
            ]
        }
    )


async def _persist_coding_round(
    session: InterviewSessionModel,
    round_state: CodingInterviewRoundModel,
    current_user: UserModel,
) -> InterviewSessionModel:
    updated = await repo.update_interview_session(
        InterviewSessionModel(
            id=session.id,
            user_id=session.user_id,
            coding_round=round_state,
        ),
        current_user.id,
    )
    if updated is None:
        raise fastapi.HTTPException(status_code=500, detail="Unable to update coding round")
    return updated


async def _finalize_completed_session(
    session: InterviewSessionModel,
    current_user: UserModel,
    *,
    transcript_entry: str | None = None,
) -> InterviewSessionModel:
    company_context = await _retrieve_company_context_text(
        company_id=session.company_id,
        company_name=session.company_name,
        query=_build_company_rag_query(
            job_description_text=session.job_description_text or "",
            role_title=session.role_title or _extract_role_title(session.job_description_text or ""),
        ),
    )
    score, report = await _generate_ai_report(session, session.answers, company_context=company_context)

    updated = await repo.update_interview_session(
        InterviewSessionModel(
            id=session.id,
            user_id=session.user_id,
            current_question_index=len(session.questions),
            score=score,
            report=report,
            is_completed=True,
            completed_at=utcnow(),
            transcript=transcript_entry,
            coding_round=(
                session.coding_round.model_copy(update={"completed_at": utcnow()})
                if session.coding_round and session.coding_round.completed_at is None
                else session.coding_round
            ),
        ),
        current_user.id,
    )
    if updated is None:
        raise fastapi.HTTPException(status_code=500, detail="Unable to finalize interview")
    return updated


def _get_markitdown():
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise fastapi.HTTPException(
            status_code=500,
            detail="MarkItDown is not installed on the backend service.",
        ) from exc
    return MarkItDown


async def _parse_document_with_markitdown(file: fastapi.UploadFile) -> ParsedDocumentResponse:
    if not file.filename:
        raise fastapi.HTTPException(status_code=400, detail="No file provided")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise fastapi.HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or 'unknown'}")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise fastapi.HTTPException(status_code=413, detail="File size exceeds 10 MB limit")

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(content)
            tmp_path = handle.name

        MarkItDown = _get_markitdown()

        def _convert() -> str:
            converter = MarkItDown(enable_plugins=False)
            result = converter.convert(tmp_path)
            return getattr(result, "text_content", "") or ""

        extracted = await fastapi.concurrency.run_in_threadpool(_convert)
    except fastapi.HTTPException:
        raise
    except Exception as exc:
        logger.exception("markitdown parse failed for %s", file.filename)
        raise fastapi.HTTPException(status_code=422, detail=f"Unable to parse document: {exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    extracted = extracted.strip()
    if not extracted:
        raise fastapi.HTTPException(status_code=422, detail="Document parsing returned no text")

    return ParsedDocumentResponse(file_name=file.filename, extracted_text=extracted)


@app.post("/api/auth/register", response_model=AuthResponse)
async def register(payload: RegisterRequest):
    email = _normalize_email(payload.email)
    existing = await auth_repo.get_user_by_email(email)
    if existing is not None:
        raise fastapi.HTTPException(status_code=409, detail="An account with this email already exists")

    try:
        user = await auth_repo.create_user(email=email, password_hash=_hash_password(payload.password))
    except sqlite3.IntegrityError as exc:
        raise fastapi.HTTPException(status_code=409, detail="An account with this email already exists") from exc

    token = _issue_access_token()
    await auth_repo.issue_token(user.id, token)
    return AuthResponse(token=token, user=user)


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest):
    email = _normalize_email(payload.email)
    user = await auth_repo.get_user_by_email(email)
    if user is None or not _verify_password(payload.password, user.password_hash):
        raise fastapi.HTTPException(status_code=401, detail="Invalid email or password")

    public_user = UserModel.model_validate(user.model_dump())
    token = _issue_access_token()
    await auth_repo.issue_token(public_user.id, token)
    return AuthResponse(token=token, user=public_user)


@app.get("/api/auth/me", response_model=UserModel)
async def get_me(current_user: UserModel = fastapi.Depends(_get_current_user)):
    return current_user


@app.post("/api/auth/logout")
async def logout(token: str = fastapi.Depends(_get_bearer_token)):
    await auth_repo.delete_token(token)
    return {"ok": True}


@app.get("/api/companies", response_model=list[CompanyModel])
async def list_companies(_: UserModel = fastapi.Depends(_get_current_user)):
    return await company_repo.list_companies()


@app.post("/api/companies", response_model=CompanyModel)
async def create_company(
    payload: CompanyCreateRequest,
    _: UserModel = fastapi.Depends(_get_current_user),
):
    try:
        return await company_repo.create_company(payload.name, payload.description, payload.website)
    except sqlite3.IntegrityError as exc:
        raise fastapi.HTTPException(status_code=409, detail="A company with this name already exists") from exc


@app.get("/api/companies/{company_id}", response_model=CompanyModel)
async def get_company(
    company_id: UUID,
    _: UserModel = fastapi.Depends(_get_current_user),
):
    company = await company_repo.get_company(company_id)
    if company is None:
        raise fastapi.HTTPException(status_code=404, detail="Company not found")
    return company


@app.post("/api/companies/{company_id}/knowledge/text", response_model=CompanyKnowledgeSourceResponse)
async def add_company_knowledge_text(
    company_id: UUID,
    payload: CompanyKnowledgeTextRequest,
    _: UserModel = fastapi.Depends(_get_current_user),
):
    company = await company_repo.get_company(company_id)
    if company is None:
        raise fastapi.HTTPException(status_code=404, detail="Company not found")

    metadata = _merge_knowledge_metadata(payload.metadata)
    source = await company_repo.create_knowledge_source(
        company_id=company.id,
        title=payload.title,
        source_type=payload.source_type,
        content=payload.content.strip(),
        metadata_json=metadata,
    )

    try:
        await fastapi.concurrency.run_in_threadpool(
            index_company_document,
            str(company.id),
            company.name,
            source.title,
            source.content,
            source.source_type,
            {
                **source.metadata_json,
                "source_id": str(source.id),
                "created_at": source.created_at.isoformat(),
            },
        )
    except Exception as exc:
        await company_repo.delete_knowledge_source(source.id)
        raise fastapi.HTTPException(status_code=502, detail=f"Unable to index company knowledge: {exc}") from exc

    return _source_to_response(source)


@app.post("/api/companies/{company_id}/knowledge/upload", response_model=CompanyKnowledgeSourceResponse)
async def upload_company_knowledge(
    company_id: UUID,
    file: fastapi.UploadFile = fastapi.File(...),
    title: str | None = fastapi.Form(default=None),
    source_type: str = fastapi.Form(...),
    metadata_json: str | None = fastapi.Form(default=None),
    _: UserModel = fastapi.Depends(_get_current_user),
):
    company = await company_repo.get_company(company_id)
    if company is None:
        raise fastapi.HTTPException(status_code=404, detail="Company not found")
    if source_type not in {"manual", "official_page", "job_description", "engineering_blog", "interview_guide"}:
        raise fastapi.HTTPException(status_code=400, detail="Unsupported source_type")

    parsed = await _parse_document_with_markitdown(file)
    metadata = _merge_knowledge_metadata(_parse_metadata_form(metadata_json))
    source = await company_repo.create_knowledge_source(
        company_id=company.id,
        title=(title or parsed.file_name).strip(),
        source_type=source_type,
        content=parsed.extracted_text,
        metadata_json=metadata,
    )

    try:
        await fastapi.concurrency.run_in_threadpool(
            index_company_document,
            str(company.id),
            company.name,
            source.title,
            source.content,
            source.source_type,
            {
                **source.metadata_json,
                "source_id": str(source.id),
                "created_at": source.created_at.isoformat(),
            },
        )
    except Exception as exc:
        await company_repo.delete_knowledge_source(source.id)
        raise fastapi.HTTPException(status_code=502, detail=f"Unable to index uploaded knowledge: {exc}") from exc

    return _source_to_response(source)


@app.get("/api/companies/{company_id}/knowledge", response_model=list[CompanyKnowledgeSourceResponse])
async def list_company_knowledge(
    company_id: UUID,
    _: UserModel = fastapi.Depends(_get_current_user),
):
    company = await company_repo.get_company(company_id)
    if company is None:
        raise fastapi.HTTPException(status_code=404, detail="Company not found")
    return [_source_to_response(source) for source in await company_repo.list_knowledge_sources(company.id)]


@app.put("/api/companies/{company_id}/knowledge/{source_id}", response_model=CompanyKnowledgeSourceResponse)
async def update_company_knowledge(
    company_id: UUID,
    source_id: UUID,
    payload: CompanyKnowledgeUpdateRequest,
    _: UserModel = fastapi.Depends(_get_current_user),
):
    company = await company_repo.get_company(company_id)
    if company is None:
        raise fastapi.HTTPException(status_code=404, detail="Company not found")

    existing = await company_repo.get_knowledge_source(source_id)
    if existing is None or existing.company_id != company.id:
        raise fastapi.HTTPException(status_code=404, detail="Knowledge source not found")

    updated = await company_repo.update_knowledge_source(
        source_id,
        title=payload.title,
        source_type=payload.source_type,
        content=payload.content.strip(),
        metadata_json=_merge_knowledge_metadata(payload.metadata),
    )
    if updated is None:
        raise fastapi.HTTPException(status_code=404, detail="Knowledge source not found")

    try:
        sources = await company_repo.list_knowledge_sources(company.id)
        await _reindex_company_knowledge(company, sources)
    except Exception as exc:
        raise fastapi.HTTPException(status_code=502, detail=f"Unable to reindex company knowledge: {exc}") from exc

    return _source_to_response(updated)


@app.delete("/api/companies/{company_id}/knowledge/{source_id}")
async def delete_company_knowledge_source(
    company_id: UUID,
    source_id: UUID,
    _: UserModel = fastapi.Depends(_get_current_user),
):
    company = await company_repo.get_company(company_id)
    if company is None:
        raise fastapi.HTTPException(status_code=404, detail="Company not found")

    existing = await company_repo.get_knowledge_source(source_id)
    if existing is None or existing.company_id != company.id:
        raise fastapi.HTTPException(status_code=404, detail="Knowledge source not found")

    await company_repo.delete_knowledge_source(source_id)

    try:
        sources = await company_repo.list_knowledge_sources(company.id)
        await _reindex_company_knowledge(company, sources)
    except Exception as exc:
        raise fastapi.HTTPException(status_code=502, detail=f"Unable to reindex company knowledge: {exc}") from exc

    return {"ok": True}


@app.post("/api/companies/{company_id}/rag/search", response_model=list[RagSearchResult])
async def search_company_knowledge(
    company_id: UUID,
    payload: RagSearchRequest,
    _: UserModel = fastapi.Depends(_get_current_user),
):
    company = await company_repo.get_company(company_id)
    if company is None:
        raise fastapi.HTTPException(status_code=404, detail="Company not found")
    try:
        results = await fastapi.concurrency.run_in_threadpool(
            retrieve_company_context,
            str(company.id),
            payload.query,
            payload.top_k,
        )
    except Exception as exc:
        raise fastapi.HTTPException(status_code=502, detail=f"Unable to search company knowledge: {exc}") from exc
    return [RagSearchResult.model_validate(item) for item in results]


@app.post("/api/interviews/parse-document", response_model=ParsedDocumentResponse)
async def parse_document(
    file: fastapi.UploadFile = fastapi.File(...),
    _: UserModel = fastapi.Depends(_get_current_user),
):
    return await _parse_document_with_markitdown(file)


@app.post("/api/interviews", response_model=InterviewSessionModel)
async def create_interview(
    payload: InterviewCreateRequest,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    resume_text = payload.resume_text.strip()
    job_description_text = payload.job_description_text.strip()
    company = await _require_company(payload.company_id) if payload.company_id else None
    target_company = (payload.target_company or "").strip() or (company.name if company else None)
    role_title_guess = _extract_role_title(job_description_text)
    company_context = await _retrieve_company_context_text(
        company_id=company.id if company else None,
        company_name=company.name if company else None,
        query=_build_company_rag_query(
            job_description_text=job_description_text,
            role_title=role_title_guess,
        ),
    )

    role_title, questions = await _generate_ai_questions(
        resume_text,
        job_description_text,
        payload.interview_length,
        company_name=company.name if company else None,
        company_context=company_context,
    )

    coding_round = await _build_coding_round(
        target_company=target_company,
        difficulty=payload.coding_difficulty,
        interviewer_mode=payload.interviewer_mode,
        preferred_language=payload.preferred_language,
        role_title=role_title,
        job_description_text=job_description_text,
    )

    record = InterviewSessionModel(
        user_id=current_user.id,
        company_id=company.id if company else None,
        company_name=company.name if company else None,
        resume_text=resume_text,
        job_description_text=job_description_text,
        interview_length=payload.interview_length,
        role_title=role_title,
        target_company=target_company,
        questions=questions,
        answers=[],
        current_question_index=0,
        coding_round=coding_round,
        is_completed=False,
    )
    return await repo.add_interview_session(record)


@app.get("/api/interviews", response_model=list[InterviewHistoryItem])
async def get_interview_history(current_user: UserModel = fastapi.Depends(_get_current_user)):
    sessions = await repo.get_all_interview_sessions(current_user.id)
    return [_history_item_from_session(session) for session in sessions]


@app.get("/api/interviews/{session_id}", response_model=InterviewSessionModel)
async def get_interview(
    session_id: UUID,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    return session


@app.post("/api/interviews/{session_id}/answer", response_model=InterviewSessionModel)
async def submit_interview_answer(
    session_id: UUID,
    payload: InterviewAnswerRequest,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.is_completed:
        raise fastapi.HTTPException(status_code=400, detail="Interview is already completed")
    if not session.questions:
        raise fastapi.HTTPException(status_code=400, detail="Interview has no questions")
    if session.current_question_index >= len(session.questions):
        raise fastapi.HTTPException(status_code=400, detail="The question stage is already complete")

    current_question = session.questions[session.current_question_index]
    answer = InterviewAnswerModel(
        question_id=current_question.id,
        question_order=current_question.order,
        category=current_question.category,
        question_prompt=current_question.prompt,
        answer_text=payload.answer_text.strip(),
    )

    updated = await repo.update_interview_session(
        InterviewSessionModel(
            id=session.id,
            user_id=session.user_id,
            answers=[*session.answers, answer],
            current_question_index=session.current_question_index + 1,
            transcript=_session_transcript_entry(current_question, answer.answer_text),
        ),
        current_user.id,
    )
    if updated is None:
        raise fastapi.HTTPException(status_code=500, detail="Unable to save interview answer")
    return updated


@app.post("/api/interviews/{session_id}/skip", response_model=InterviewSessionModel)
async def skip_interview_question(
    session_id: UUID,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.is_completed:
        raise fastapi.HTTPException(status_code=400, detail="Interview is already completed")
    if not session.questions:
        raise fastapi.HTTPException(status_code=400, detail="Interview has no questions")
    if session.current_question_index >= len(session.questions):
        raise fastapi.HTTPException(status_code=400, detail="The question stage is already complete")

    current_question = session.questions[session.current_question_index]
    skipped_answer = InterviewAnswerModel(
        question_id=current_question.id,
        question_order=current_question.order,
        category=current_question.category,
        question_prompt=current_question.prompt,
        answer_text="[Skipped by candidate]",
    )

    updated = await repo.update_interview_session(
        InterviewSessionModel(
            id=session.id,
            user_id=session.user_id,
            answers=[*session.answers, skipped_answer],
            current_question_index=session.current_question_index + 1,
            transcript=_session_transcript_entry(current_question, skipped_answer.answer_text),
        ),
        current_user.id,
    )
    if updated is None:
        raise fastapi.HTTPException(status_code=500, detail="Unable to skip interview question")

    if updated.current_question_index < len(updated.questions) or updated.coding_round is not None:
        return updated
    return await _finalize_completed_session(updated, current_user)


@app.post("/api/interviews/{session_id}/practice-duration", response_model=InterviewSessionModel)
async def record_practice_duration(
    session_id: UUID,
    payload: PracticeDurationUpdateRequest,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.is_completed:
        return session

    updated = await repo.increment_practice_duration(session_id, payload.seconds, current_user.id)
    if updated is None:
        raise fastapi.HTTPException(status_code=500, detail="Unable to record practice duration")
    return updated


@app.post("/api/interviews/{session_id}/coding/events", response_model=InterviewSessionModel)
async def append_coding_event(
    session_id: UUID,
    payload: CodingEventRequest,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.coding_round is None:
        raise fastapi.HTTPException(status_code=400, detail="Coding round is not enabled for this interview")
    if session.is_completed:
        raise fastapi.HTTPException(status_code=400, detail="Interview is already completed")

    updated_round = _append_coding_round_state(
        session.coding_round,
        event=payload.event,
        code=payload.code,
        language=payload.language,
        transcript_append=payload.transcript_append,
    )
    return await _persist_coding_round(session, updated_round, current_user)


@app.post("/api/interviews/{session_id}/coding/realtime/session", response_model=CodingRealtimeSessionResponse)
async def create_coding_realtime_session(
    session_id: UUID,
    payload: CodingRealtimeSessionRequest,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.coding_round is None or session.coding_round.problem is None:
        raise fastapi.HTTPException(status_code=400, detail="Coding round is not enabled for this interview")
    if session.is_completed:
        raise fastapi.HTTPException(status_code=400, detail="Interview is already completed")

    selected_voice = (payload.voice or os.getenv("OPENAI_REALTIME_VOICE") or "marin").strip() or "marin"
    sdp_answer = await _create_realtime_call(
        sdp_offer=payload.sdp,
        voice=selected_voice,
        current_user=current_user,
    )
    return CodingRealtimeSessionResponse(
        sdp=sdp_answer,
        model=get_realtime_model(),
        voice=selected_voice,
        transcription_model=get_realtime_transcription_model(),
    )


@app.post("/api/interviews/{session_id}/coding/intervention", response_model=CodingInterventionResponse)
async def decide_coding_intervention(
    session_id: UUID,
    payload: CodingInterventionRequest,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.coding_round is None or session.coding_round.problem is None:
        raise fastapi.HTTPException(status_code=400, detail="Coding round is not enabled for this interview")
    if payload.problem_id != session.coding_round.problem.id:
        raise fastapi.HTTPException(status_code=400, detail="Problem mismatch for coding round")

    working_round = _append_coding_round_state(
        session.coding_round,
        code=payload.code,
        language=payload.language,
        transcript_append=payload.transcript_recent,
    )
    if payload.recent_events:
        for event in payload.recent_events:
            working_round = _append_coding_round_state(working_round, event=event)
            if event.type in {"candidate_spoke", "clarification_asked", "solution_explained"} and event.transcript_excerpt:
                working_round = _append_coding_conversation_turn(
                    working_round,
                    role="candidate",
                    content=event.transcript_excerpt,
                    source_event_type=event.type,
                )

    decision = intervention_engine.decide(
        round_state=working_round,
        transcript_recent=payload.transcript_recent,
        recent_events=payload.recent_events,
        elapsed_time_seconds=payload.elapsed_time_seconds,
        code=payload.code,
    )

    reply = await _generate_coding_interviewer_reply(
        round_state=working_round,
        recent_events=payload.recent_events,
        transcript_recent=payload.transcript_recent,
        code=payload.code,
        decision=decision,
    )

    persisted_round = apply_intervention(working_round, decision)
    if reply:
        source_event_type = payload.recent_events[-1].type if payload.recent_events else None
        reply_kind = "intervention" if decision.should_interrupt else "reply"
        persisted_round = _append_coding_conversation_turn(
            persisted_round,
            role="interviewer",
            content=reply,
            kind=reply_kind,
            source_event_type=source_event_type,
            severity=decision.severity if decision.should_interrupt else None,
        )
    updated_session = await _persist_coding_round(session, persisted_round, current_user)

    return CodingInterventionResponse(
        should_interrupt=decision.should_interrupt,
        reason=decision.reason,
        question=decision.question,
        severity=decision.severity,
        reply=reply,
        coding_round=updated_session.coding_round,
    )


@app.post("/api/interviews/{session_id}/finish", response_model=InterviewSessionModel)
async def finish_interview(
    session_id: UUID,
    payload: InterviewFinishRequest,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.is_completed:
        return session
    if not session.questions:
        raise fastapi.HTTPException(status_code=400, detail="Interview has no questions")

    if session.current_question_index < len(session.questions):
        answer_text = (payload.answer_text or "").strip()
        if not answer_text:
            raise fastapi.HTTPException(status_code=400, detail="Answer text is required for the active question")

        current_question = session.questions[session.current_question_index]
        final_answer = InterviewAnswerModel(
            question_id=current_question.id,
            question_order=current_question.order,
            category=current_question.category,
            question_prompt=current_question.prompt,
            answer_text=answer_text,
        )
        updated = await repo.update_interview_session(
            InterviewSessionModel(
                id=session.id,
                user_id=session.user_id,
                answers=[*session.answers, final_answer],
                current_question_index=session.current_question_index + 1,
                transcript=_session_transcript_entry(current_question, final_answer.answer_text),
            ),
            current_user.id,
        )
        if updated is None:
            raise fastapi.HTTPException(status_code=500, detail="Unable to advance the interview")
        if updated.current_question_index < len(updated.questions) or updated.coding_round is not None:
            return updated
        return await _finalize_completed_session(updated, current_user)

    active_coding_round = session.coding_round
    if active_coding_round is not None:
        completed_round = _append_coding_round_state(
            active_coding_round,
            code=payload.code,
            language=payload.language,
            transcript_append=payload.transcript_recent,
        )
        evaluation = await _generate_ai_coding_evaluation(completed_round)
        finalized_round = completed_round.model_copy(
            update={
                "evaluation": evaluation,
                "completed_at": utcnow(),
            }
        )
        session = session.model_copy(update={"coding_round": finalized_round})

    return await _finalize_completed_session(session, current_user)


@app.delete("/api/interviews/{session_id}")
async def delete_interview(
    session_id: UUID,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    deleted = await repo.delete_interview_session(session_id, current_user.id)
    if not deleted:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    return {"ok": True}


@app.post("/api/interviews/{session_id}/hint", response_model=InterviewHelpResponse)
async def get_question_hint(
    session_id: UUID,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.is_completed or session.current_question_index >= len(session.questions):
        raise fastapi.HTTPException(status_code=400, detail="No active question available")

    question = session.questions[session.current_question_index]
    company_context = await _retrieve_company_context_text(
        company_id=session.company_id,
        company_name=session.company_name,
        query=_build_company_rag_query(
            job_description_text=session.job_description_text or "",
            role_title=session.role_title or _extract_role_title(session.job_description_text or ""),
            question_prompt=question.prompt,
        ),
        top_k=4,
    )
    content = await _generate_ai_help("hint", session, question, company_context=company_context)
    return InterviewHelpResponse(question_id=question.id, content=content)


@app.post("/api/interviews/{session_id}/model-answer", response_model=InterviewHelpResponse)
async def get_question_model_answer(
    session_id: UUID,
    current_user: UserModel = fastapi.Depends(_get_current_user),
):
    session = await repo.get_interview_session(session_id, current_user.id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.is_completed or session.current_question_index >= len(session.questions):
        raise fastapi.HTTPException(status_code=400, detail="No active question available")

    question = session.questions[session.current_question_index]
    company_context = await _retrieve_company_context_text(
        company_id=session.company_id,
        company_name=session.company_name,
        query=_build_company_rag_query(
            job_description_text=session.job_description_text or "",
            role_title=session.role_title or _extract_role_title(session.job_description_text or ""),
            question_prompt=question.prompt,
        ),
        top_k=4,
    )
    content = await _generate_ai_help("model_answer", session, question, company_context=company_context)
    return InterviewHelpResponse(question_id=question.id, content=content)


@app.get("/api/interview-data/sessions/{session_id}", response_model=InterviewSessionModel)
async def get_interview_session(session_id: UUID):
    return await repo.ensure_session(session_id)


@app.post("/api/interview-data/sessions/{session_id}", response_model=InterviewSessionModel)
async def create_or_get_interview_session(session_id: UUID):
    return await repo.ensure_session(session_id)


@app.post("/api/interview-data/sessions/{session_id}/turn", response_model=InterviewSessionModel)
async def append_interview_session_turn(session_id: UUID, payload: SessionTurnUpdate):
    try:
        return await repo.append_turn(session_id, payload)
    except RuntimeError as exc:
        raise fastapi.HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/interview-data/sessions/{session_id}/complete", response_model=InterviewSessionModel)
async def complete_interview_session(session_id: UUID):
    await repo.ensure_session(session_id)
    updated = await repo.complete_interview_session(session_id)
    if updated is None:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")
    return updated


@app.post("/api/interview-data/add_interview_session", response_model=InterviewSessionModel)
async def add_interview_session_tool(payload: InterviewSessionRecordRequest):
    return await repo.add_interview_session(payload.record)


@app.get("/api/interview-data/get_interview_sessions", response_model=list[InterviewSessionModel])
async def get_interview_sessions_tool():
    return await repo.get_all_interview_sessions()


@app.get("/api/interview-data/get_interview_session/{session_id}", response_model=InterviewSessionModel | None)
async def get_interview_session_tool(session_id: UUID):
    return await repo.get_interview_session(session_id)


@app.post("/api/interview-data/update_interview_session", response_model=InterviewSessionModel | None)
async def update_interview_session_tool(payload: InterviewSessionRecordRequest):
    return await repo.update_interview_session(payload.record)


@app.post("/api/interview-data/complete_interview_session/{session_id}", response_model=InterviewSessionModel | None)
async def complete_interview_session_tool(session_id: UUID):
    return await repo.complete_interview_session(session_id)


@app.post("/api/upload")
async def upload_file(file: fastapi.UploadFile = fastapi.File(...)):
    if not file.filename:
        raise fastapi.HTTPException(status_code=400, detail="No file provided")

    trace_id = uuid.uuid4().hex[:12]
    agent_url = f"{get_agent_base_url()}/upload"
    content = await file.read()

    files = {
        "file": (file.filename, content, file.content_type or "application/octet-stream"),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(agent_url, files=files, headers={"x-trace-id": trace_id})
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or "Upload failed"
        raise fastapi.HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise fastapi.HTTPException(status_code=502, detail="Agent upload service unavailable") from exc

    return response.json()


@app.get("/api/uploads/{file_id}/{file_name}")
async def get_uploaded_file(file_id: str, file_name: str):
    trace_id = uuid.uuid4().hex[:12]
    agent_url = f"{get_agent_base_url()}/uploads/{file_id}/{file_name}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(agent_url, headers={"x-trace-id": trace_id})
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or "File not found"
        raise fastapi.HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise fastapi.HTTPException(status_code=502, detail="Agent file service unavailable") from exc

    return fastapi.Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/octet-stream"),
        headers={
            "Content-Disposition": response.headers.get("Content-Disposition", f'inline; filename="{file_name}"'),
        },
    )


if not os.path.exists("static"):
    @app.get("/", response_class=fastapi.responses.HTMLResponse)
    async def root():
        return "API service is running. Navigate to <a href='/health'>/health</a> for health checks."


@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    return "Healthy"


if os.path.exists("static"):
    app.mount(
        "/",
        fastapi.staticfiles.StaticFiles(directory="static", html=True),
        name="static",
    )
