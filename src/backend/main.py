import contextlib
import json
import logging
import os
import uuid
from typing import Any, AsyncIterator

import fastapi
import fastapi.responses
import fastapi.staticfiles
import httpx
import opentelemetry.instrumentation.fastapi as otel_fastapi
import telemetry
from pydantic import BaseModel, Field


@contextlib.asynccontextmanager
async def lifespan(app):
    telemetry.configure_opentelemetry()
    yield


app = fastapi.FastAPI(lifespan=lifespan)
otel_fastapi.FastAPIInstrumentor.instrument_app(app, exclude_spans=["send"])


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are a professional interview coach who helps the user prepare "
    "for behavioral and technical interview questions."
)


def get_agent_base_url() -> str:
    return (
        os.getenv("INTERVIEW_PREP_AGENTS_URL")
        or os.getenv("AGENT_HTTPS")
        or os.getenv("AGENT_HTTP")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


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
    return f"data: {json.dumps(payload)}\\n\\n"


async def _read_agent_stream(
    response: httpx.Response,
) -> AsyncIterator[dict[str, Any]]:
    is_sse = "text/event-stream" in response.headers.get("content-type", "")

    if not is_sse:
        async for chunk in response.aiter_text():
            if chunk:
                yield {"type": "delta", "delta": chunk}
        return

    async for raw_line in response.aiter_lines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue

        data = line[5:].strip()
        if not data:
            continue

        parsed: Any
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            yield {"type": "delta", "delta": data}
            continue

        event_type = parsed.get("type") if isinstance(parsed, dict) else None

        if event_type == "RUN_ERROR":
            yield {"type": "error", "error": parsed.get("message") or parsed.get("error")}
            return

        if event_type in {"RUN_FINISHED", "RUN_COMPLETED", "done", "complete", "end"}:
            yield {"type": "done"}
            return

        delta_text = _extract_text(parsed)
        if delta_text:
            yield {"type": "delta", "delta": delta_text}

        # Keep compatibility with non-AGUI streams.
        if event_type in {"error", "done", "complete", "end"}:
            yield {"type": "done" if event_type != "error" else "error", "error": parsed.get("error")}
            return


@app.post("/api/session/new", response_model=StartSessionResponse)
async def start_session() -> StartSessionResponse:
    return StartSessionResponse(sessionId=str(uuid.uuid4()), systemPrompt=SYSTEM_PROMPT)


@app.post("/api/upload")
async def upload_file(file: fastapi.UploadFile = fastapi.File(...)):
    if not file.filename:
        raise fastapi.HTTPException(status_code=400, detail="No file provided")

    agent_url = f"{get_agent_base_url()}/upload"
    content = await file.read()

    files = {
        "file": (file.filename, content, file.content_type or "application/octet-stream"),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(agent_url, files=files)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or "Upload failed"
        raise fastapi.HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise fastapi.HTTPException(status_code=502, detail="Agent upload service unavailable") from exc

    return response.json()


@app.get("/api/uploads/{file_id}/{file_name}")
async def get_uploaded_file(file_id: str, file_name: str):
    agent_url = f"{get_agent_base_url()}/uploads/{file_id}/{file_name}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(agent_url)
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
    agent_payload = {
        "thread_id": payload.sessionId,
        "run_id": uuid.uuid4().hex,
        "messages": [message.model_dump() for message in payload.history]
        + [{"role": "user", "content": payload.message}],
    }

    async def event_generator() -> AsyncIterator[str]:
        yield _to_sse({"type": "start"})

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{get_agent_base_url()}/ag-ui",
                    json=agent_payload,
                    headers={"accept": "text/event-stream"},
                ) as response:
                    response.raise_for_status()
                    async for event in _read_agent_stream(response):
                        if event.get("type") == "error":
                            err = event.get("error") or "Agent stream failed"
                            yield _to_sse({"type": "error", "error": err})
                            return
                        if event.get("type") == "done":
                            yield _to_sse({"type": "done"})
                            return
                        yield _to_sse(event)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text or "Agent stream request failed"
            yield _to_sse({"type": "error", "error": detail})
            return
        except httpx.HTTPError:
            yield _to_sse({"type": "error", "error": "Agent service unavailable"})
            return

        yield _to_sse({"type": "done"})

    return fastapi.responses.StreamingResponse(event_generator(), media_type="text/event-stream")


if not os.path.exists("static"):
    @app.get("/", response_class=fastapi.responses.HTMLResponse)
    async def root():
        """Root endpoint."""
        return "API service is running. Navigate to <a href='/health'>/health</a> for health checks."


@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"


# Serve static files directly from root, if the "static" directory exists
if os.path.exists("static"):
    app.mount(
        "/",
        fastapi.staticfiles.StaticFiles(directory="static", html=True),
        name="static"
    )
