from __future__ import annotations

import logging
import os
from uuid import UUID
import httpx

from fastapi import FastAPI
import fastapi
from mcp.server.fastmcp import FastMCP
from models import InterviewSessionModel
from contextlib import asynccontextmanager

logger = logging.getLogger("interviewdata")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

mcp = FastMCP("InterviewData", stateless_http=True, json_response=True)
BACKEND_BASE_URL = (
    os.getenv("BACKEND_URL")
    or os.getenv("BACKEND_HTTP")
    or "http://127.0.0.1:8002"
).rstrip("/")


async def _get_json(path: str):
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{BACKEND_BASE_URL}{path}")
        response.raise_for_status()
        return response.json()


async def _post_json(path: str, payload: dict | None = None):
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{BACKEND_BASE_URL}{path}", json=payload)
        response.raise_for_status()
        return response.json()


@mcp.tool(name="add_interview_session")
async def add_interview_session(record: InterviewSessionModel) -> InterviewSessionModel:
    data = await _post_json("/api/interview-data/add_interview_session", {"record": record.model_dump(mode="json")})
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="get_interview_sessions")
async def get_interview_sessions() -> list[InterviewSessionModel]:
    data = await _get_json("/api/interview-data/get_interview_sessions")
    return [InterviewSessionModel.model_validate(item) for item in data]


@mcp.tool(name="get_interview_session")
async def get_interview_session(id: UUID) -> InterviewSessionModel | None:
    data = await _get_json(f"/api/interview-data/get_interview_session/{id}")
    if data is None:
        return None
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="update_interview_session")
async def update_interview_session(record: InterviewSessionModel) -> InterviewSessionModel | None:
    data = await _post_json("/api/interview-data/update_interview_session", {"record": record.model_dump(mode="json")})
    if data is None:
        return None
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="complete_interview_session")
async def complete_interview_session(id: UUID) -> InterviewSessionModel | None:
    data = await _post_json(f"/api/interview-data/complete_interview_session/{id}")
    if data is None:
        return None
    return InterviewSessionModel.model_validate(data)
    

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting interview-data service")

    async with mcp.session_manager.run():
        yield

app = FastAPI(title="interview-data-mcp", lifespan=lifespan)


@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"


@app.get("/sessions/{session_id}", response_model=InterviewSessionModel)
async def get_session(session_id: UUID):
    data = await _get_json(f"/api/interview-data/sessions/{session_id}")
    return InterviewSessionModel.model_validate(data)


@app.post("/sessions/{session_id}", response_model=InterviewSessionModel)
async def create_or_get_session(session_id: UUID):
    data = await _post_json(f"/api/interview-data/sessions/{session_id}")
    return InterviewSessionModel.model_validate(data)


@app.post("/sessions/{session_id}/turn", response_model=InterviewSessionModel)
async def append_session_turn(session_id: UUID, payload: dict):
    data = await _post_json(f"/api/interview-data/sessions/{session_id}/turn", payload)
    return InterviewSessionModel.model_validate(data)


@app.post("/sessions/{session_id}/complete", response_model=InterviewSessionModel)
async def complete_session(session_id: UUID):
    data = await _post_json(f"/api/interview-data/sessions/{session_id}/complete")
    return InterviewSessionModel.model_validate(data)


app.mount("/interview-data", mcp.streamable_http_app())