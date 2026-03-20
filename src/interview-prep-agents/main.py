import os
import uuid
import time
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Dict, Tuple
from agents import build_workflow_agent
import logging
import fastapi
import fastapi.responses
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from agent_framework import AgentSession
from agent_framework.openai import OpenAIChatClient
from agent_framework.ag_ui import AgentFrameworkAgent, add_agent_framework_fastapi_endpoint
from contextlib import asynccontextmanager
import sys

uploaded_files: Dict[str, Tuple[bytes, str, str]] = {}
allowed_extensions = {".pdf", ".docx", ".doc", ".txt", ".md", ".html"}

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("interview-prep-agents")

provider = os.getenv("LLM_PROVIDER", "github").strip().lower()

workflow_agent = None
client = None


class _ThreadAgentState:
    def __init__(self, agent: Any):
        self.agent = agent
        self.lock = asyncio.Lock()


class ThreadScopedAgentRouter:
    """Route runs to per-thread workflow agents for multi-user concurrency."""

    def __init__(self, agent_factory: Callable[[], Awaitable[Any]]):
        self.id: str = f"thread-router-{uuid.uuid4().hex[:8]}"
        self.name: str | None = "Interview Coach Router"
        self.description: str | None = "Routes AG-UI runs to thread-scoped workflow agents"
        self._agent_factory = agent_factory
        self._agents_by_thread: dict[str, _ThreadAgentState] = {}
        self._registry_lock = asyncio.Lock()

    async def _get_or_create_thread_agent(self, thread_id: str) -> _ThreadAgentState:
        existing = self._agents_by_thread.get(thread_id)
        if existing is not None:
            return existing

        async with self._registry_lock:
            existing = self._agents_by_thread.get(thread_id)
            if existing is not None:
                return existing

            logger.info("agent router creating workflow for thread_id=%s", thread_id)
            agent = await self._agent_factory()
            state = _ThreadAgentState(agent)
            self._agents_by_thread[thread_id] = state
            return state

    async def _refresh_thread_agent(self, thread_id: str) -> _ThreadAgentState:
        async with self._registry_lock:
            logger.warning("agent router rebuilding workflow for thread_id=%s after finalization timeout", thread_id)
            agent = await self._agent_factory()
            state = _ThreadAgentState(agent)
            self._agents_by_thread[thread_id] = state
            return state

    @staticmethod
    def _resolve_thread_id(session: AgentSession | None) -> str:
        if session is not None:
            metadata = getattr(session, "metadata", None)
            if isinstance(metadata, dict):
                value = metadata.get("ag_ui_thread_id")
                if isinstance(value, str) and value:
                    return value

            service_session_id = getattr(session, "service_session_id", None)
            if isinstance(service_session_id, str) and service_session_id:
                return service_session_id

        return "default"

    async def _run_stream_for_thread(
        self,
        messages: Any,
        *,
        session: AgentSession | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        thread_id = self._resolve_thread_id(session)
        thread_state = await self._get_or_create_thread_agent(thread_id)

        if thread_state.lock.locked():
            logger.warning("agent thread busy; waiting thread_id=%s", thread_id)

        async with thread_state.lock:
            pending = getattr(thread_state.agent, "pending_requests", None)
            if isinstance(pending, dict) and pending:
                logger.warning(
                    "clearing %s pending workflow request_info entries for thread_id=%s",
                    len(pending),
                    thread_id,
                )
                pending.clear()

            max_attempts = 10
            for attempt in range(1, max_attempts + 1):
                try:
                    stream = thread_state.agent.run(messages, stream=True, session=session, **kwargs)
                    async for update in stream:
                        yield update
                    return
                except RuntimeError as exc:
                    if "Workflow is already running" not in str(exc) or attempt == max_attempts:
                        if "Workflow is already running" not in str(exc):
                            raise
                        break

                    delay_s = 0.2
                    logger.warning(
                        "workflow still finalizing for thread_id=%s; retrying in %.2fs (attempt %s/%s)",
                        thread_id,
                        delay_s,
                        attempt,
                        max_attempts,
                    )
                    await asyncio.sleep(delay_s)

            # Last resort: replace stuck workflow instance for this thread.
            # Context is preserved by backend history replay.
            thread_state = await self._refresh_thread_agent(thread_id)
            stream = thread_state.agent.run(messages, stream=True, session=session, **kwargs)
            async for update in stream:
                yield update

    async def _run_non_stream_for_thread(
        self,
        messages: Any,
        *,
        session: AgentSession | None = None,
        **kwargs: Any,
    ) -> Any:
        thread_id = self._resolve_thread_id(session)
        thread_state = await self._get_or_create_thread_agent(thread_id)

        async with thread_state.lock:
            pending = getattr(thread_state.agent, "pending_requests", None)
            if isinstance(pending, dict) and pending:
                logger.warning(
                    "clearing %s pending workflow request_info entries for thread_id=%s",
                    len(pending),
                    thread_id,
                )
                pending.clear()

            max_attempts = 10
            for attempt in range(1, max_attempts + 1):
                try:
                    return await thread_state.agent.run(messages, stream=False, session=session, **kwargs)
                except RuntimeError as exc:
                    if "Workflow is already running" not in str(exc) or attempt == max_attempts:
                        if "Workflow is already running" not in str(exc):
                            raise
                        break

                    delay_s = 0.2
                    logger.warning(
                        "workflow still finalizing for thread_id=%s (non-stream); retrying in %.2fs (attempt %s/%s)",
                        thread_id,
                        delay_s,
                        attempt,
                        max_attempts,
                    )
                    await asyncio.sleep(delay_s)

            thread_state = await self._refresh_thread_agent(thread_id)
            return await thread_state.agent.run(messages, stream=False, session=session, **kwargs)

    def run(self, messages: Any = None, *, stream: bool = False, session: AgentSession | None = None, **kwargs: Any) -> Any:
        if stream:
            return self._run_stream_for_thread(messages, session=session, **kwargs)
        return self._run_non_stream_for_thread(messages, session=session, **kwargs)

    def create_session(self, **kwargs: Any) -> AgentSession:
        return AgentSession(**kwargs)

    def get_session(self, *, service_session_id: str, **kwargs: Any) -> AgentSession:
        return AgentSession(service_session_id=service_session_id, **kwargs)


def build_chat_client() -> tuple[OpenAIChatClient, str, str]:
    if provider == "github":
        github_token = os.getenv("GITHUB_MODELS_TOKEN", "")
        github_model = os.getenv("GITHUB_MODELS_MODEL", "openai/gpt-4.1")

        if not github_token:
            raise RuntimeError("GITHUB_MODELS_TOKEN is required when LLM_PROVIDER=github")

        return (
            OpenAIChatClient(
                api_key=github_token,
                model_id=github_model,
                base_url="https://models.github.ai/inference",
                default_headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": os.getenv("GITHUB_MODELS_API_VERSION", "2022-11-28"),
                },
            ),
            "github",
            github_model,
        )

    if provider == "openai":
        openai_api_key = os.getenv("OPENAI_API_KEY", "")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        if not openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        return (
            OpenAIChatClient(
                api_key=openai_api_key,
                model_id=openai_model,
                base_url=openai_base_url,
            ),
            "openai",
            openai_model,
        )

    raise RuntimeError("LLM_PROVIDER must be either 'github' or 'openai'")


def patch_opentelemetry_detach() -> None:
    """Suppress only benign cross-context detach errors from workflow stream teardown."""
    try:
        from opentelemetry import context as otel_context
        from opentelemetry import trace as otel_trace
    except Exception:
        return

    current_detach = getattr(otel_context, "detach", None)
    runtime_context = getattr(otel_context, "_RUNTIME_CONTEXT", None)
    if current_detach is None or runtime_context is None:
        return
    if getattr(current_detach, "_interview_simulator_patched", False):
        return

    def safe_detach(token: object) -> None:
        try:
            runtime_context.detach(token)
        except ValueError as exc:
            if "different Context" in str(exc):
                return
            logger.exception("Failed to detach context")
        except Exception:
            logger.exception("Failed to detach context")

    setattr(safe_detach, "_interview_simulator_patched", True)
    otel_context.detach = safe_detach
    trace_context_api = getattr(otel_trace, "__dict__", {}).get("context_api")
    if trace_context_api is not None and getattr(trace_context_api, "detach", None) is not None:
        trace_context_api.detach = safe_detach

@asynccontextmanager
async def lifespan(app: FastAPI):
    global workflow_agent
    global client

    client, active_provider, active_model = build_chat_client()
    patch_opentelemetry_detach()

    logger.info("Agent startup: provider=%s model=%s", active_provider, active_model)
    workflow_agent = ThreadScopedAgentRouter(lambda: build_workflow_agent(client))
    agui_agent = AgentFrameworkAgent(agent=workflow_agent, require_confirmation=False)
    add_agent_framework_fastapi_endpoint(app, agui_agent, path="/ag-ui")
    logger.info("Agent startup complete: AG-UI endpoint mounted at /ag-ui")
    yield

app = FastAPI(title="Interview Coach Agent", lifespan=lifespan)


@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()

    logger.info("[trace=%s] agent http start method=%s path=%s", trace_id, request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "[trace=%s] agent http error method=%s path=%s duration_ms=%.2f",
            trace_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise

    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "[trace=%s] agent http end method=%s path=%s status=%s duration_ms=%.2f",
        trace_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["x-trace-id"] = trace_id
    return response

@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex[:12]
    logger.info("[trace=%s] agent upload start filename=%s", trace_id, file.filename)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=415, detail=f"File type '{ext}' is not supported.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File size exceeds 10 MB limit.")

    file_id = uuid.uuid4().hex
    content_type = file.content_type or "application/octet-stream"
    uploaded_files[file_id] = (content, content_type, file.filename)

    url = str(request.base_url).rstrip("/") + f"/uploads/{file_id}/{file.filename}"
    logger.info("[trace=%s] agent upload complete file_id=%s size=%s url=%s", trace_id, file_id, len(content), url)
    return JSONResponse({"url": url})


@app.get("/uploads/{file_id}/{file_name}")
async def get_upload(file_id: str, file_name: str):
    logger.info("agent upload fetch file_id=%s file_name=%s", file_id, file_name)
    entry = uploaded_files.get(file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")

    content, content_type, original_name = entry
    headers = {"Content-Disposition": f'inline; filename="{original_name}"'}
    return Response(content=content, media_type=content_type, headers=headers)