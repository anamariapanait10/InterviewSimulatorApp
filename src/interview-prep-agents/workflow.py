import os
import importlib
import uuid
import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("interview-prep-agents.workflow")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
BACKEND_BASE_URL = (
    os.getenv("BACKEND_HTTP")
    or "http://127.0.0.1:8002"
).rstrip("/")
INTERVIEW_DATA_API_PREFIX = "/api/interview-data"


INTAKE_INSTRUCTIONS = (
    "You are an interview coach intake assistant. "
    "Collect the candidate's target role, experience level, and interview goals. "
    "If the user shared resume/job-description links, acknowledge them and use their context."
)


INTERVIEWER_INSTRUCTIONS = (
    "You are an interview coach. "
    "Run a realistic interview with one question at a time. "
    "Mix behavioral and technical prompts based on the user's role. "
    "After each user response, give concise coaching feedback and the next question."
)


_router_agent: Any | None = None
_session_locks: dict[str, asyncio.Lock] = {}
_session_locks_guard = asyncio.Lock()


async def _post_json_with_diagnostics(
    *,
    operation: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace_id = uuid.uuid4().hex[:12]
    timeout = httpx.Timeout(connect=3.0, read=40.0, write=20.0, pool=5.0)
    started_at = time.perf_counter()

    logger.info("backend request start trace=%s op=%s url=%s", trace_id, operation, url)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "backend request ok trace=%s op=%s status=%s elapsed_ms=%.2f",
                trace_id,
                operation,
                response.status_code,
                elapsed_ms,
            )
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"Backend returned non-object JSON for op={operation}")
            return data
    except httpx.TimeoutException as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.error(
            "backend request timeout trace=%s op=%s url=%s elapsed_ms=%.2f",
            trace_id,
            operation,
            url,
            elapsed_ms,
        )
        raise RuntimeError(
            f"Backend timeout during {operation} ({url}) after {elapsed_ms:.2f} ms"
        ) from exc
    except httpx.HTTPStatusError as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        detail = exc.response.text or ""
        logger.error(
            "backend request status error trace=%s op=%s url=%s status=%s elapsed_ms=%.2f detail=%s",
            trace_id,
            operation,
            url,
            exc.response.status_code,
            elapsed_ms,
            detail,
        )
        raise RuntimeError(
            f"Backend status error during {operation}: {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.error(
            "backend request transport error trace=%s op=%s url=%s elapsed_ms=%.2f error=%s",
            trace_id,
            operation,
            url,
            elapsed_ms,
            str(exc),
        )
        raise RuntimeError(
            f"Backend transport error during {operation} ({url}): {exc}"
        ) from exc


def _build_router_agent() -> Any:
    global _router_agent
    if _router_agent is not None:
        return _router_agent

    try:
        agents_sdk = importlib.import_module("agents")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenAI Agents SDK is not installed. Install dependency 'openai-agents'."
        ) from exc

    Agent = agents_sdk.Agent

    intake_agent = Agent(
        name="intake",
        instructions=INTAKE_INSTRUCTIONS,
        model=OPENAI_MODEL,
    )

    interviewer_agent = Agent(
        name="interviewer",
        instructions=INTERVIEWER_INSTRUCTIONS,
        model=OPENAI_MODEL,
    )

    _router_agent = Agent(
        name="interview_router",
        model=OPENAI_MODEL,
        instructions=(
            "You route interview-coach turns. "
            "Use intake for onboarding/setup and interviewer for active interview practice."
        ),
        handoffs=[intake_agent, interviewer_agent],
    )
    return _router_agent


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history:
        role = str(item.get("role", "")).strip().lower()
        content = item.get("content")
        if role not in {"system", "user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _extract_attachment_links(message: str) -> tuple[str | None, str | None]:
    text = message.lower()
    resume_link: str | None = None
    job_description_link: str | None = None

    for line in message.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("attachment url:"):
            continue
        value = stripped.split(":", 1)[1].strip()
        if not value:
            continue

        if "resume" in text and resume_link is None:
            resume_link = value
        elif any(key in text for key in ("job", "jd", "description")) and job_description_link is None:
            job_description_link = value
        elif resume_link is None:
            resume_link = value
        elif job_description_link is None:
            job_description_link = value

    return resume_link, job_description_link


async def _ensure_and_load_session(session_id: str) -> dict[str, Any]:
    session_uuid = str(uuid.UUID(session_id))
    url = f"{BACKEND_BASE_URL}{INTERVIEW_DATA_API_PREFIX}/sessions/{session_uuid}"
    return await _post_json_with_diagnostics(
        operation="ensure_and_load_session",
        url=url,
    )


def _build_context_system_message(session: dict[str, Any]) -> dict[str, str]:
    resume_link = session.get("resume_link") or "none"
    job_link = session.get("job_description_link") or "none"
    transcript = session.get("transcript") or ""
    transcript_tail = transcript[-1600:] if transcript else ""

    return {
        "role": "system",
        "content": (
            "Interview session context from persistence layer. "
            f"resume_link={resume_link}; job_description_link={job_link}. "
            "Use this context to keep continuity across turns. "
            f"Transcript tail:\n{transcript_tail}"
        ),
    }


async def _append_turn(
    *,
    session_id: str,
    user_message: str,
    assistant_message: str,
    resume_link: str | None,
    job_description_link: str | None,
) -> None:
    session_uuid = str(uuid.UUID(session_id))
    payload = {
        "user_message": user_message,
        "assistant_message": assistant_message,
        "resume_link": resume_link,
        "job_description_link": job_description_link,
    }
    url = f"{BACKEND_BASE_URL}{INTERVIEW_DATA_API_PREFIX}/sessions/{session_uuid}/turn"
    await _post_json_with_diagnostics(
        operation="append_turn",
        url=url,
        payload=payload,
    )


async def _get_session_lock(session_id: str) -> asyncio.Lock:
    existing = _session_locks.get(session_id)
    if existing is not None:
        return existing

    async with _session_locks_guard:
        existing = _session_locks.get(session_id)
        if existing is not None:
            return existing

        lock = asyncio.Lock()
        _session_locks[session_id] = lock
        return lock


async def run_text_turn(*, message: str, history: list[dict[str, Any]], session_id: str) -> str:
    try:
        agents_sdk = importlib.import_module("agents")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenAI Agents SDK is not installed. Install dependency 'openai-agents'."
        ) from exc

    Runner = agents_sdk.Runner
    router_agent = _build_router_agent()

    lock = await _get_session_lock(session_id)
    async with lock:
        session = await _ensure_and_load_session(session_id)

        convo = _normalize_history(history)
        convo.insert(0, _build_context_system_message(session))
        convo.append({"role": "user", "content": message})

        result = await Runner.run(
            router_agent,
            input=convo,
            context={"session_id": session_id},
        )

        final_output = getattr(result, "final_output", "")
        if isinstance(final_output, str):
            final_text = final_output
        elif final_output is None:
            final_text = ""
        else:
            final_text = str(final_output)

        resume_link, job_description_link = _extract_attachment_links(message)
        await _append_turn(
            session_id=session_id,
            user_message=message,
            assistant_message=final_text,
            resume_link=resume_link,
            job_description_link=job_description_link,
        )

        return final_text
