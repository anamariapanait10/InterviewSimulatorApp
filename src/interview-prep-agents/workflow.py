import os
import importlib
import uuid
import asyncio
import logging
import time
import sys
from typing import Any, cast

import httpx
from agents.mcp import MCPServerStreamableHttp
from agents import Runner, Agent
logger = logging.getLogger("interview-prep-agents.workflow")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
BACKEND_BASE_URL = (
    os.getenv("BACKEND_URL")
    or os.getenv("BACKEND_HTTP")
    or ""
).rstrip("/")
BACKEND_INTERVIEW_DATA_API_PREFIX = "/api/interview-data"

INTERVIEW_DATA_MCP_URL = os.getenv("INTERVIEW_DATA_HTTP") or "http://127.0.0.1:8002"
INTERVIEW_DATA_MCP_URL = INTERVIEW_DATA_MCP_URL + "/interview-data"
print(f"Interview Data MCP URL: {INTERVIEW_DATA_MCP_URL}", file=sys.stderr)

MARKITDOWN_BASE_URL = (
    os.getenv("MCP_MARKITDOWN_HTTP")
    or os.getenv("MARKITDOWN_MCP_URL")
    or "http://127.0.0.1:3001"
).rstrip("/")

_orchestrator_agent: Any | None = None
_session_locks: dict[str, asyncio.Lock] = {}
_session_locks_guard = asyncio.Lock()
_mcp_servers: list[Any] = []
_mcp_lock = asyncio.Lock()
_mcp_initialized = False


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


def _build_orchestrator_agent() -> Any:
    global _orchestrator_agent
    if _orchestrator_agent is not None:
        return _orchestrator_agent

    behavioral_agent = Agent(
        name="behavioral",
        instructions=(
            "You are a behavioral interviewer. "
            "Ask STAR-method questions tailored to the candidate's background. "
            "Use InterviewData tools to read session context and store answers. "
            "Ask one question at a time. "
            "When the behavioral portion is done, hand off to the technical interviewer. "
            "If the user asks for setup help or changes topic unexpectedly, hand back to the orchestrator."
        ),
        model=OPENAI_MODEL,
        mcp_servers=_mcp_servers,
    )

    technical_agent = Agent(
        name="technical",
        instructions=(
            """
            "You are a technical interviewer. "
            "Ask role-specific technical questions based on the stored resume and job description. "
            "Use InterviewData tools to read session state and save the candidate's answers. "
            "Ask one question at a time. "
            "When the technical round is complete, hand off to the summarizer. "
            "If the conversation goes off-path, hand back to the orchestrator."
            """
        ),
        model=OPENAI_MODEL,
        mcp_servers=_mcp_servers,
    )
    
    summarizer = Agent(
        name="summarizer",
        instructions=(
            "You are the interview summarizer. "
            "Use InterviewData tools to review the full session and generate a final assessment. "
            "Summarize strengths, weaknesses, behavioral performance, technical performance, "
            "and 3-5 concrete improvement suggestions. "
            "After delivering the summary, explain that the interview is complete and greet the user."
        ),
        mcp_servers=_mcp_servers,
    )

    _orchestrator_agent = Agent(
        name="orchestrator",
        instructions=(
            """
            You are the Interview Orchestrator for an AI Interview Coach system.

            Your job is to:
            1. Review the FULL conversation history
            2. Determine which interview phases are already complete
            3. Fetch the interview session from the interview data MCP server
            4. Collect and store the user's resume and job description. If the user hasn't provided them, ask the user for their resume and job description (link or text).
            5. The user may proceed without a resume or without a job description if they choose.
            6. Use MarkItDown to parse document links into markdown.
            7. Store the resume and job description in the session record using the interview data MCP server.
            8. Hand off to the correct specialist agent at the right time

            You do NOT conduct behavioural or technical interviews yourself.
            You do NOT generate the final summary yourself.
            Your role is orchestration, intake, and routing.

            Interview phase sequence:
            1. Reception / session setup / document intake
            2. Behavioural Interviewer
            3. Technical Interviewer
            4. Summariser

            IMPORTANT:
            - Always review the FULL conversation history before deciding what to do.
            - Do NOT route to an agent whose phase has already been completed.
            - When a specialist hands back, treat that phase as COMPLETE and advance to the next one.
            - If the user explicitly requests a specific phase, honour that request.
            - If the user wants to end, hand off to "summariser".
            - If the user's request is unexpected or unclear, briefly ask what they'd like to do.

            Routing rules (apply in order, skipping completed phases):
            - If session setup or document intake has NOT been completed
                → handle it yourself first
            - If intake is complete and behavioural interview has NOT started
                → hand off to "behavioural_interviewer"
            - If behavioural interview is complete and technical interview has NOT started
                → hand off to "technical_interviewer"
            - If technical interview is complete
                → hand off to "summariser"
            - If the user wants to end early
                → hand off to "summariser"
            - If the user explicitly requests a specific phase
                → honour that request

            Tone:
            - Be brief
            - Be supportive
            - Be encouraging
            - Let specialist agents do the detailed interview work

            Only perform detailed intake/session setup yourself.
            All interview questioning and summarisation should be handled by the specialist agents.
        """
        ),
        model=OPENAI_MODEL,
        mcp_servers=_mcp_servers,
        handoffs=[behavioral_agent, technical_agent, summarizer],
    )

    return _orchestrator_agent


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


def _to_mcp_endpoint(base_url: str) -> str:
    return base_url if base_url.endswith("/mcp") else f"{base_url}/mcp"


async def initialize_mcp_servers() -> None:
    global _mcp_initialized
    if _mcp_initialized:
        return

    async with _mcp_lock:
        if _mcp_initialized:
            return

        servers: list[Any] = [
            MCPServerStreamableHttp(
                params={"url": _to_mcp_endpoint(MARKITDOWN_BASE_URL)},
                cache_tools_list=True,
                name="markitdown",
                client_session_timeout_seconds=30,
            ),
            MCPServerStreamableHttp(
                params={"url": _to_mcp_endpoint(INTERVIEW_DATA_MCP_URL)},
                cache_tools_list=True,
                name="interview_data",
                client_session_timeout_seconds=30,
            ),
        ]

        for server in servers:
            await server.connect()

        _mcp_servers.clear()
        _mcp_servers.extend(servers)
        _mcp_initialized = True
        logger.info(
            "MCP servers initialized markitdown=%s",
            _to_mcp_endpoint(MARKITDOWN_BASE_URL),
        )


async def cleanup_mcp_servers() -> None:
    global _mcp_initialized
    async with _mcp_lock:
        for server in _mcp_servers:
            try:
                await server.cleanup()
            except Exception:
                logger.exception("MCP cleanup failed")
        _mcp_servers.clear()
        _mcp_initialized = False


async def _ensure_and_load_session(session_id: str) -> dict[str, Any]:
    session_uuid = str(uuid.UUID(session_id))
    url = f"{BACKEND_BASE_URL}{BACKEND_INTERVIEW_DATA_API_PREFIX}/sessions/{session_uuid}"
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
    resume_text: str | None = None,
    job_description_text: str | None = None,
) -> None:
    session_uuid = str(uuid.UUID(session_id))
    payload = {
        "user_message": user_message,
        "assistant_message": assistant_message,
        "resume_link": resume_link,
        "job_description_link": job_description_link,
        "resume_text": resume_text,
        "job_description_text": job_description_text,
    }
    url = f"{BACKEND_BASE_URL}{BACKEND_INTERVIEW_DATA_API_PREFIX}/sessions/{session_uuid}/turn"
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
    await initialize_mcp_servers()

    try:
        agents_sdk = importlib.import_module("agents")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenAI Agents SDK is not installed. Install dependency 'openai-agents'."
        ) from exc

    router_agent = _build_orchestrator_agent()

    lock = await _get_session_lock(session_id)
    async with lock:
        session = await _ensure_and_load_session(session_id)

        convo = _normalize_history(history)
        convo.insert(0, _build_context_system_message(session))
        convo.append({"role": "user", "content": message})

        result = await Runner.run(
            router_agent,
            input=cast(Any, convo),
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
            resume_text=None,
            job_description_text=None,
        )

        return final_text
