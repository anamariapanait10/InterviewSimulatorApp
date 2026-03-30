import os
import json
import logging
import fastapi
import fastapi.responses
from fastapi import FastAPI
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager

from workflow import run_text_turn
from upload_routes import router as upload_router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("interview-prep-agents")

for key, value in os.environ.items():
    logger.info("Env var %s=%s", key, value)


class ChatInputMessage(BaseModel):
    role: str
    content: str


class ChatStreamRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    history: list[ChatInputMessage] = Field(default_factory=list)


def _to_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("OpenAI agent runtime startup complete")
    yield

app = FastAPI(title="Interview Coach Agent", lifespan=lifespan)
app.include_router(upload_router)


@app.post("/chat/stream")
async def stream_chat(payload: ChatStreamRequest):
    async def event_generator():
        yield _to_sse({"type": "start", "sessionId": payload.session_id})
        try:
            answer = await run_text_turn(
                message=payload.message,
                history=[m.model_dump() for m in payload.history],
                session_id=payload.session_id,
            )
            if answer:
                yield _to_sse({"type": "delta", "delta": answer})
            yield _to_sse({"type": "done"})
        except Exception as exc:
            logger.exception("text turn failed")
            yield _to_sse({"type": "error", "error": str(exc) or "Agent execution failed"})

    return fastapi.responses.StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"


