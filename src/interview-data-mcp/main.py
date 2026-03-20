from __future__ import annotations

import contextlib
import logging
import os
import time
from uuid import UUID

from fastapi import FastAPI, Request
import fastapi
from mcp.server.fastmcp import FastMCP
import sys
from db import Base, engine
from models import InterviewSessionModel
from repository import InterviewSessionRepository
from contextlib import asynccontextmanager

logger = logging.getLogger("interviewdata")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

repo = InterviewSessionRepository()
mcp = FastMCP("InterviewData", stateless_http=True, json_response=True)


@mcp.tool(name="add_interview_session")
async def add_interview_session(record: InterviewSessionModel) -> InterviewSessionModel:
    """Adds an interview session to database."""
    result = await repo.add_interview_session(record)
    logger.info("Added interview session with ID '%s'", result.id)
    return result


@mcp.tool(name="get_interview_sessions")
async def get_interview_sessions() -> list[InterviewSessionModel]:
    """Gets a list of interview sessions from database."""
    sessions = await repo.get_all_interview_sessions()
    logger.info("Retrieved %s interview sessions.", len(sessions))
    return sessions


@mcp.tool(name="get_interview_session")
async def get_interview_session(id: UUID) -> InterviewSessionModel | None:
    """Gets an interview session from the database by ID."""
    record = await repo.get_interview_session(id)
    if record is None:
        logger.warning("Interview session with ID '%s' not found.", id)
        return None
    logger.info("Retrieved interview session with ID '%s'", id)
    return record


@mcp.tool(name="update_interview_session")
async def update_interview_session(record: InterviewSessionModel) -> InterviewSessionModel | None:
    """Updates an interview session in the database."""
    updated = await repo.update_interview_session(record)
    if updated is None:
        logger.warning("Interview session with ID '%s' not found.", record.id)
        return None
    logger.info("Updated interview session with ID '%s'", record.id)
    return updated


@mcp.tool(name="complete_interview_session")
async def complete_interview_session(id: UUID) -> InterviewSessionModel | None:
    """Completes an interview session in the database."""
    completed = await repo.complete_interview_session(id)
    if completed is None:
        logger.warning("Interview session with ID '%s' not found.", id)
        return None
    logger.info("Completed interview session '%s'", id)
    return completed
    

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[startup] Starting up database connection", file=sys.stderr, flush=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("[startup] Initializing MCP tools", file=sys.stderr, flush=True)
    async with mcp.session_manager.run():
        yield

app = FastAPI(title="interview-data-mcp", lifespan=lifespan)


@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id", "-")
    start = time.perf_counter()
    logger.info("[trace=%s] HTTP start method=%s path=%s", trace_id, request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "[trace=%s] HTTP error method=%s path=%s duration_ms=%.2f",
            trace_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "[trace=%s] HTTP end method=%s path=%s status=%s duration_ms=%.2f",
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


app.mount("/interview-data", mcp.streamable_http_app())