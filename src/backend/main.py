import contextlib
import json
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from statistics import mean
from typing import Any, AsyncIterator
from uuid import UUID

import fastapi
import fastapi.responses
import fastapi.staticfiles
import httpx
import opentelemetry.instrumentation.fastapi as otel_fastapi
import telemetry
from pydantic import BaseModel, Field

from interview_data_store import (
    InterviewAnswerModel,
    InterviewQuestionFeedbackModel,
    InterviewQuestionModel,
    InterviewReportModel,
    InterviewSessionModel,
    InterviewSessionRepository,
    SessionTurnUpdate,
    utcnow,
)


repo = InterviewSessionRepository()


@contextlib.asynccontextmanager
async def lifespan(app):
    telemetry.configure_opentelemetry()
    await repo.init_db()
    yield


app = fastapi.FastAPI(lifespan=lifespan)
otel_fastapi.FastAPIInstrumentor.instrument_app(app, exclude_spans=["send"])


logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


SYSTEM_PROMPT = (
    "You are a professional interview coach who helps the user prepare "
    "for behavioral and technical interview questions."
)

INTERVIEW_LENGTH_OPTIONS: dict[str, dict[str, int]] = {
    "short": {"behavioral": 2, "technical": 2},
    "medium": {"behavioral": 4, "technical": 4},
    "long": {"behavioral": 6, "technical": 6},
}
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html"}
ACTION_VERBS = {
    "built",
    "created",
    "delivered",
    "designed",
    "drove",
    "improved",
    "implemented",
    "launched",
    "led",
    "optimized",
    "reduced",
    "resolved",
    "scaled",
    "shipped",
}
STAR_HINTS = {"situation", "task", "action", "result", "challenge", "outcome", "impact"}
TECH_SIGNAL_WORDS = {
    "architecture",
    "latency",
    "monitoring",
    "performance",
    "reliability",
    "scalability",
    "security",
    "testing",
    "tradeoff",
    "trade-off",
}
COMMON_TECH_SKILLS = [
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "angular",
    "vue",
    "node.js",
    "node",
    "fastapi",
    "django",
    "flask",
    "spring",
    "sql",
    "postgresql",
    "mysql",
    "mongodb",
    "redis",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "terraform",
    "graphql",
    "rest",
    "microservices",
    "ci/cd",
    "git",
    "linux",
    "pandas",
    "machine learning",
    "data engineering",
    "spark",
    "airflow",
    "c#",
    ".net",
]


def get_agent_base_url() -> str:
    return (
        os.getenv("INTERVIEW_PREP_AGENTS_URL")
        or os.getenv("AGENT_HTTPS")
        or os.getenv("AGENT_HTTP")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


def get_openai_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


class ChatInputMessage(BaseModel):
    role: str
    content: str


class StartSessionResponse(BaseModel):
    sessionId: str
    systemPrompt: str


class ChatStreamRequest(BaseModel):
    sessionId: str = Field(min_length=1)
    message: str = Field(min_length=1)
    history: list[ChatInputMessage] = Field(default_factory=list)


class InterviewSessionRecordRequest(BaseModel):
    record: InterviewSessionModel


class VoiceSessionRequest(BaseModel):
    voice: str = "alloy"
    model: str = os.getenv("OPENAI_MODEL", "gpt-4o-realtime-preview")
    instructions: str | None = None


class ParsedDocumentResponse(BaseModel):
    file_name: str
    extracted_text: str


class InterviewCreateRequest(BaseModel):
    resume_text: str = Field(min_length=1)
    job_description_text: str = Field(min_length=1)
    interview_length: str = Field(pattern="^(short|medium|long)$")


class InterviewAnswerRequest(BaseModel):
    answer_text: str = Field(min_length=1)


class InterviewHistoryItem(BaseModel):
    id: str
    role_title: str
    interview_length: str | None = None
    question_count: int
    answered_count: int
    is_completed: bool
    score: int | None = None
    created_at: str
    completed_at: str | None = None


def _extract_text(event_payload: Any) -> str:
    if isinstance(event_payload, str):
        return event_payload

    if not isinstance(event_payload, dict):
        return ""

    direct = event_payload.get("delta") or event_payload.get("text") or event_payload.get("content")
    if isinstance(direct, str):
        return direct

    if isinstance(direct, list):
        flattened = []
        for item in direct:
            if isinstance(item, str):
                flattened.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                flattened.append(item["text"])
        if flattened:
            return "".join(flattened)

    message = event_payload.get("message")
    if isinstance(message, dict):
        nested = message.get("content") or message.get("text")
        if isinstance(nested, str):
            return nested

    output = event_payload.get("output")
    if isinstance(output, str):
        return output

    return ""


def _to_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


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


def _extract_skill_keywords(resume_text: str, job_description_text: str, limit: int = 6) -> list[str]:
    combined = f"{resume_text}\n{job_description_text}".lower()
    found: list[str] = []
    for skill in COMMON_TECH_SKILLS:
        if skill.lower() in combined and skill not in found:
            found.append(skill)
        if len(found) >= limit:
            return found

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#/:-]{2,}", combined)
    stop_words = {
        "about",
        "across",
        "candidate",
        "company",
        "customer",
        "deliver",
        "experience",
        "interview",
        "manage",
        "product",
        "project",
        "responsible",
        "strong",
        "team",
        "teams",
        "work",
    }
    for token in tokens:
        if token in stop_words or token in found or token.isdigit():
            continue
        found.append(token)
        if len(found) >= limit:
            break
    return found or ["problem solving", "system design", "collaboration"]


def _extract_resume_focus(resume_text: str) -> str:
    lines = [line.strip(" -*") for line in resume_text.splitlines() if line.strip()]
    for line in lines:
        if len(line.split()) < 6:
            continue
        return _safe_excerpt(line, 120)
    return "recent experience"


def _build_behavioral_questions(role_title: str, resume_text: str, count: int) -> list[InterviewQuestionModel]:
    background = _extract_resume_focus(resume_text)
    templates = [
        f"Tell me about a time you used your {background} to deliver a meaningful result. What was the situation, what actions did you take, and what changed because of your work?",
        f"Describe a moment when priorities shifted while you were working toward a {role_title} goal. How did you adapt and keep the work moving?",
        f"Walk me through a situation where you had to influence teammates or stakeholders without direct authority. What approach did you use and what was the outcome?",
        f"Share an example of a setback or failure from your previous work. How did you respond, and what did you learn that would make you stronger in this role?",
        f"Describe a time when you had to balance speed with quality on a deadline-sensitive project. How did you make tradeoffs and communicate them?",
        f"Tell me about a time you improved a process, workflow, or collaboration habit. What problem were you solving and how did you measure success?",
    ]
    return [
        InterviewQuestionModel(
            id=f"behavioral-{index + 1}",
            order=index + 1,
            category="behavioral",
            prompt=templates[index],
        )
        for index in range(count)
    ]


def _build_technical_questions(
    role_title: str,
    resume_text: str,
    job_description_text: str,
    count: int,
) -> list[InterviewQuestionModel]:
    skills = _extract_skill_keywords(resume_text, job_description_text, limit=max(count, 6))
    jd_excerpt = _safe_excerpt(job_description_text, 180)
    templates = [
        "The job description emphasizes {skill}. How would you apply it in a real {role_title} scenario, and what tradeoffs would you watch closely?",
        "Imagine you inherit a partially working feature area tied to {skill}. How would you diagnose the current state, de-risk changes, and ship improvements safely?",
        "Describe how you would design or structure a solution around {skill} for this team. What would you optimize for first, and why?",
        "What failure modes or edge cases do you associate with {skill}, and how would you test or monitor for them in production?",
        "Based on this brief from the role, `{jd_excerpt}`, what technical questions would you ask before implementation, and how would those answers shape your design?",
        "Tell me about a technically challenging problem related to {skill}. How would you break it down, prioritize the work, and validate the final result?",
    ]

    questions: list[InterviewQuestionModel] = []
    for index in range(count):
        skill = skills[index % len(skills)]
        prompt = templates[index % len(templates)].format(
            skill=skill,
            role_title=role_title,
            jd_excerpt=jd_excerpt,
        )
        questions.append(
            InterviewQuestionModel(
                id=f"technical-{index + 1}",
                order=len(questions) + 1,
                category="technical",
                prompt=prompt,
            )
        )
    return questions


def _generate_fallback_questions(
    resume_text: str,
    job_description_text: str,
    interview_length: str,
) -> tuple[str, list[InterviewQuestionModel]]:
    counts = INTERVIEW_LENGTH_OPTIONS[interview_length]
    role_title = _extract_role_title(job_description_text)
    behavioral = _build_behavioral_questions(role_title, resume_text, counts["behavioral"])
    technical = _build_technical_questions(role_title, resume_text, job_description_text, counts["technical"])

    questions: list[InterviewQuestionModel] = []
    for question in behavioral + technical:
        questions.append(
            InterviewQuestionModel(
                id=question.id,
                order=len(questions) + 1,
                category=question.category,
                prompt=question.prompt,
            )
        )

    return role_title, questions


async def _post_agent_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    trace_id = uuid.uuid4().hex[:12]
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{get_agent_base_url()}{path}",
            json=payload,
            headers={"x-trace-id": trace_id},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Agent service returned a non-object response")
        return data


async def _generate_ai_questions(
    resume_text: str,
    job_description_text: str,
    interview_length: str,
) -> tuple[str, list[InterviewQuestionModel]] | None:
    counts = INTERVIEW_LENGTH_OPTIONS[interview_length]
    try:
        payload = await _post_agent_json(
            "/interview/plan",
            {
                "resume_text": resume_text,
                "job_description_text": job_description_text,
                "interview_length": interview_length,
                "behavioral_count": counts["behavioral"],
                "technical_count": counts["technical"],
            },
        )
    except Exception:
        logger.exception("agent interview plan failed; using fallback generation")
        return None

    role_title = _to_sentence_case(str(payload.get("role_title") or "")) or _extract_role_title(job_description_text)
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        return None

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
        return None

    return role_title, questions


def _score_answer(answer_text: str, category: str, question_prompt: str, skill_keywords: list[str]) -> tuple[int, str]:
    cleaned = answer_text.strip()
    words = re.findall(r"\b[\w+#./-]+\b", cleaned)
    word_count = len(words)
    lowered = cleaned.lower()

    score = 2
    if word_count >= 35:
        score += 2
    if word_count >= 80:
        score += 2
    if any(char.isdigit() for char in cleaned):
        score += 1
    if any(verb in lowered for verb in ACTION_VERBS):
        score += 1

    if category == "behavioral":
        if sum(1 for hint in STAR_HINTS if hint in lowered) >= 2:
            score += 2
        feedback = (
            "Your answer becomes stronger when it clearly lays out the situation, the action you personally took, "
            "and the measurable result."
        )
    else:
        relevant_keywords = {item.lower() for item in skill_keywords}
        relevant_keywords.update(word.lower() for word in re.findall(r"\b[\w+#./-]+\b", question_prompt) if len(word) > 4)
        overlap = sum(1 for token in relevant_keywords if token and token in lowered)
        if overlap >= 2:
            score += 2
        if any(signal in lowered for signal in TECH_SIGNAL_WORDS):
            score += 1
        feedback = (
            "Your technical answer is strongest when it explains the tradeoffs, the implementation approach, "
            "and how you would validate the solution in practice."
        )

    score = max(1, min(score, 10))
    return score, feedback


def _build_fallback_report(
    role_title: str,
    resume_text: str,
    job_description_text: str,
    answers: list[InterviewAnswerModel],
) -> tuple[int, InterviewReportModel]:
    skill_keywords = _extract_skill_keywords(resume_text, job_description_text, limit=8)
    feedback_items: list[InterviewQuestionFeedbackModel] = []
    behavioral_scores: list[int] = []
    technical_scores: list[int] = []
    answer_lengths = [len(re.findall(r"\b[\w+#./-]+\b", answer.answer_text)) for answer in answers]

    for answer in answers:
        score, default_feedback = _score_answer(
            answer.answer_text,
            answer.category,
            answer.question_prompt,
            skill_keywords,
        )
        if answer.category == "behavioral":
            behavioral_scores.append(score)
        else:
            technical_scores.append(score)

        word_count = len(re.findall(r"\b[\w+#./-]+\b", answer.answer_text))
        if word_count < 45:
            detail = "Add more context and concrete detail so the evaluator can understand your decision-making."
        elif score >= 8:
            detail = "This answer showed strong structure and specificity. Keep that level of precision throughout the interview."
        else:
            detail = default_feedback

        feedback_items.append(
            InterviewQuestionFeedbackModel(
                question_id=answer.question_id,
                score=score,
                feedback=detail,
            )
        )

    all_scores = [item.score for item in feedback_items] or [5]
    overall_score = int(round(mean(all_scores) * 10))
    behavioral_avg = mean(behavioral_scores) if behavioral_scores else 5.0
    technical_avg = mean(technical_scores) if technical_scores else 5.0
    average_length = mean(answer_lengths) if answer_lengths else 0.0

    strengths: list[str] = []
    improvements: list[str] = []

    if average_length >= 75:
        strengths.append("You gave developed answers instead of relying on one-line responses.")
    if behavioral_avg >= 7.0:
        strengths.append("Your behavioral stories showed ownership and tangible outcomes.")
    if technical_avg >= 7.0:
        strengths.append("Your technical answers demonstrated practical thinking and solution framing.")
    if not strengths:
        strengths.append("You stayed engaged through the full interview flow and completed every question.")

    if behavioral_avg < 7.0:
        improvements.append("Use a tighter STAR structure so behavioral answers land with clearer context, action, and impact.")
    if technical_avg < 7.0:
        improvements.append("Explain technical tradeoffs more explicitly, especially around testing, failure modes, and scale.")
    if average_length < 55:
        improvements.append("Expand your answers with more evidence, metrics, and implementation detail.")
    if not improvements:
        improvements.append("Push the next iteration further by connecting each answer more directly to the target role.")

    summary = (
        f"You completed a {len(answers)}-question interview simulation for a {role_title.lower()} track "
        f"with an overall score of {overall_score}/100."
    )
    recommendation = (
        "You are trending toward interview-readiness, but your next gains will come from sharper examples and "
        "clearer technical tradeoff explanations."
        if overall_score < 80
        else "You are performing at a strong mock-interview level. Keep sharpening precision and role-specific depth."
    )

    report = InterviewReportModel(
        summary=summary,
        strengths=strengths,
        improvements=improvements,
        behavioral_feedback=(
            f"Behavioral performance averaged {behavioral_avg:.1f}/10. "
            "Your stories improve when you make the stakes, your individual actions, and the measurable result explicit."
        ),
        technical_feedback=(
            f"Technical performance averaged {technical_avg:.1f}/10. "
            "The strongest answers connected architecture choices to practical tradeoffs and validation steps."
        ),
        communication_feedback=(
            "Your communication is strongest when you use concise structure up front and then add concrete evidence. "
            "Avoid drifting into abstract statements without examples."
        ),
        recommendation=recommendation,
        question_feedback=feedback_items,
    )
    return overall_score, report


async def _generate_ai_report(
    session: InterviewSessionModel,
    answers: list[InterviewAnswerModel],
) -> tuple[int, InterviewReportModel] | None:
    try:
        payload = await _post_agent_json(
            "/interview/report",
            {
                "resume_text": session.resume_text or "",
                "job_description_text": session.job_description_text or "",
                "interview_length": session.interview_length or "medium",
                "role_title": session.role_title or _extract_role_title(session.job_description_text or ""),
                "questions": [question.model_dump(mode="json") for question in session.questions],
                "answers": [answer.model_dump(mode="json") for answer in answers],
            },
        )
    except Exception:
        logger.exception("agent interview report failed; using fallback report")
        return None

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
        )
        score = int(payload.get("score"))
    except Exception:
        return None

    if not report.summary or not report.recommendation:
        return None

    return max(1, min(score, 100)), report


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
        question_count=len(session.questions),
        answered_count=len(session.answers),
        is_completed=session.is_completed,
        score=session.score,
        created_at=session.created_at.isoformat(),
        completed_at=session.completed_at.isoformat() if session.completed_at else None,
    )


async def _read_agent_stream(
    response: httpx.Response,
    *,
    trace_id: str,
) -> AsyncIterator[dict[str, Any]]:
    is_sse = "text/event-stream" in response.headers.get("content-type", "")
    logger.debug("[trace=%s] agent stream opened is_sse=%s", trace_id, is_sse)

    if not is_sse:
        async for chunk in response.aiter_text():
            if chunk:
                yield {"type": "delta", "delta": chunk}
        return

    pending_data_lines: list[str] = []

    def _flush_event_data(lines: list[str]) -> str:
        if not lines:
            return ""
        return "\n".join(lines).strip()

    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")

        if line == "":
            data = _flush_event_data(pending_data_lines)
            pending_data_lines = []
            if not data:
                continue

            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                logger.debug("[trace=%s] dropped malformed sse chunk", trace_id)
                continue

            event_type = parsed.get("type") if isinstance(parsed, dict) else None
            normalized_event_type = str(event_type or "").upper()

            if normalized_event_type in {"RUN_ERROR", "ERROR"}:
                yield {"type": "error", "error": parsed.get("message") or parsed.get("error")}
                return

            if normalized_event_type in {"RUN_FINISHED", "RUN_COMPLETED", "DONE", "COMPLETE", "END"}:
                yield {"type": "done"}
                return

            if normalized_event_type in {"DELTA", "TEXT_MESSAGE_CONTENT"}:
                delta_text = parsed.get("delta")
                if isinstance(delta_text, str) and delta_text:
                    yield {"type": "delta", "delta": delta_text}
                continue

            if normalized_event_type == "START":
                continue

            if normalized_event_type:
                continue

            delta_text = _extract_text(parsed)
            if delta_text:
                yield {"type": "delta", "delta": delta_text}
            continue

        if line.startswith(":"):
            continue

        if line.startswith("data:"):
            pending_data_lines.append(line[5:].lstrip())

    trailing = _flush_event_data(pending_data_lines)
    if trailing:
        try:
            parsed = json.loads(trailing)
        except json.JSONDecodeError:
            logger.debug("[trace=%s] dropped malformed trailing sse chunk", trace_id)
            return

        event_type = parsed.get("type") if isinstance(parsed, dict) else None
        normalized_event_type = str(event_type or "").upper()
        if normalized_event_type in {"DELTA", "TEXT_MESSAGE_CONTENT"}:
            delta_text = parsed.get("delta")
            if isinstance(delta_text, str) and delta_text:
                yield {"type": "delta", "delta": delta_text}
        elif normalized_event_type in {"RUN_ERROR", "ERROR"}:
            yield {"type": "error", "error": parsed.get("message") or parsed.get("error")}
        elif normalized_event_type in {"RUN_FINISHED", "RUN_COMPLETED", "DONE", "COMPLETE", "END"}:
            yield {"type": "done"}


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


@app.post("/api/session/new", response_model=StartSessionResponse)
async def start_session() -> StartSessionResponse:
    return StartSessionResponse(sessionId=str(uuid.uuid4()), systemPrompt=SYSTEM_PROMPT)


@app.post("/api/interviews/parse-document", response_model=ParsedDocumentResponse)
async def parse_document(file: fastapi.UploadFile = fastapi.File(...)):
    return await _parse_document_with_markitdown(file)


@app.post("/api/interviews", response_model=InterviewSessionModel)
async def create_interview(payload: InterviewCreateRequest):
    resume_text = payload.resume_text.strip()
    job_description_text = payload.job_description_text.strip()

    generated = await _generate_ai_questions(resume_text, job_description_text, payload.interview_length)
    if generated is None:
        role_title, questions = _generate_fallback_questions(
            resume_text,
            job_description_text,
            payload.interview_length,
        )
    else:
        role_title, questions = generated

    record = InterviewSessionModel(
        resume_text=resume_text,
        job_description_text=job_description_text,
        interview_length=payload.interview_length,
        role_title=role_title,
        questions=questions,
        answers=[],
        current_question_index=0,
        is_completed=False,
    )
    return await repo.add_interview_session(record)


@app.get("/api/interviews", response_model=list[InterviewHistoryItem])
async def get_interview_history():
    sessions = await repo.get_all_interview_sessions()
    return [_history_item_from_session(session) for session in sessions]


@app.get("/api/interviews/{session_id}", response_model=InterviewSessionModel)
async def get_interview(session_id: UUID):
    session = await repo.get_interview_session(session_id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    return session


@app.post("/api/interviews/{session_id}/answer", response_model=InterviewSessionModel)
async def submit_interview_answer(session_id: UUID, payload: InterviewAnswerRequest):
    session = await repo.get_interview_session(session_id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.is_completed:
        raise fastapi.HTTPException(status_code=400, detail="Interview is already completed")
    if not session.questions:
        raise fastapi.HTTPException(status_code=400, detail="Interview has no questions")
    if session.current_question_index >= len(session.questions):
        raise fastapi.HTTPException(status_code=400, detail="Interview has no remaining questions")
    if session.current_question_index == len(session.questions) - 1:
        raise fastapi.HTTPException(status_code=400, detail="Use the finish endpoint for the final question")

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
            answers=[*session.answers, answer],
            current_question_index=session.current_question_index + 1,
            transcript=_session_transcript_entry(current_question, answer.answer_text),
        )
    )
    if updated is None:
        raise fastapi.HTTPException(status_code=500, detail="Unable to save interview answer")
    return updated


@app.post("/api/interviews/{session_id}/finish", response_model=InterviewSessionModel)
async def finish_interview(session_id: UUID, payload: InterviewAnswerRequest):
    session = await repo.get_interview_session(session_id)
    if session is None:
        raise fastapi.HTTPException(status_code=404, detail="Interview not found")
    if session.is_completed:
        return session
    if not session.questions:
        raise fastapi.HTTPException(status_code=400, detail="Interview has no questions")
    if session.current_question_index != len(session.questions) - 1:
        raise fastapi.HTTPException(status_code=400, detail="Finish is only available on the last question")

    current_question = session.questions[session.current_question_index]
    final_answer = InterviewAnswerModel(
        question_id=current_question.id,
        question_order=current_question.order,
        category=current_question.category,
        question_prompt=current_question.prompt,
        answer_text=payload.answer_text.strip(),
    )
    completed_answers = [*session.answers, final_answer]

    generated_report = await _generate_ai_report(session, completed_answers)
    if generated_report is None:
        score, report = _build_fallback_report(
            session.role_title or _extract_role_title(session.job_description_text or ""),
            session.resume_text or "",
            session.job_description_text or "",
            completed_answers,
        )
    else:
        score, report = generated_report

    updated = await repo.update_interview_session(
        InterviewSessionModel(
            id=session.id,
            answers=completed_answers,
            current_question_index=len(session.questions),
            score=score,
            report=report,
            is_completed=True,
            completed_at=utcnow(),
            transcript=_session_transcript_entry(current_question, final_answer.answer_text),
        )
    )
    if updated is None:
        raise fastapi.HTTPException(status_code=500, detail="Unable to finalize interview")
    return updated


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


@app.post("/api/chat/stream")
async def stream_chat(payload: ChatStreamRequest):
    trace_id = uuid.uuid4().hex[:12]
    replay_history = [
        message.model_dump()
        for message in payload.history
        if message.role in {"system", "user", "assistant"}
    ]

    agent_payload = {
        "session_id": payload.sessionId,
        "messages": replay_history + [{"role": "user", "content": payload.message}],
        "message": payload.message,
        "history": replay_history,
    }

    async def event_generator() -> AsyncIterator[str]:
        yield _to_sse({"type": "start", "traceId": trace_id})
        done_emitted = False

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{get_agent_base_url()}/chat/stream",
                    json=agent_payload,
                    headers={"accept": "text/event-stream", "x-trace-id": trace_id},
                ) as response:
                    response.raise_for_status()
                    async for event in _read_agent_stream(response, trace_id=trace_id):
                        if event.get("type") == "error":
                            err = event.get("error") or "Agent stream failed"
                            logger.warning("[trace=%s] agent stream error=%s", trace_id, _truncate(err))
                            yield _to_sse({"type": "error", "error": err, "traceId": trace_id})
                            return
                        if event.get("type") == "done":
                            if not done_emitted:
                                yield _to_sse({"type": "done"})
                                done_emitted = True
                            continue
                        yield _to_sse(event)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text or "Agent stream request failed"
            logger.warning("[trace=%s] agent stream status error=%s", trace_id, _truncate(detail))
            yield _to_sse({"type": "error", "error": detail, "traceId": trace_id})
            return
        except httpx.HTTPError:
            logger.warning("[trace=%s] agent service unavailable", trace_id)
            yield _to_sse({"type": "error", "error": "Agent service unavailable", "traceId": trace_id})
            return

        if not done_emitted:
            yield _to_sse({"type": "done"})

    return fastapi.responses.StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/voice/session")
async def create_voice_session(payload: VoiceSessionRequest):
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise fastapi.HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    trace_id = uuid.uuid4().hex[:12]
    instructions = payload.instructions or (
        "You are an interview coach voice agent. "
        "Keep replies concise and practical. "
        "Ask one interview question at a time and provide coaching feedback."
    )

    session_request = {
        "model": payload.model,
        "voice": payload.voice,
        "modalities": ["audio", "text"],
        "instructions": instructions,
    }

    realtime_url = f"{get_openai_base_url()}/realtime/sessions"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                realtime_url,
                json=session_request,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "OpenAI-Beta": "realtime=v1",
                    "x-trace-id": trace_id,
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or "Failed to create voice session"
        logger.warning("[trace=%s] voice session status error=%s", trace_id, _truncate(detail))
        raise fastapi.HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        logger.warning("[trace=%s] voice session unavailable", trace_id)
        raise fastapi.HTTPException(status_code=502, detail="OpenAI Realtime unavailable") from exc
    except Exception as exc:
        logger.exception("[trace=%s] unexpected error creating voice session", trace_id)
        raise fastapi.HTTPException(status_code=500, detail="Unexpected error creating voice session") from exc

    return response.json()


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
