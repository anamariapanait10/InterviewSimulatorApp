from __future__ import annotations

import logging
import os
from uuid import UUID

from fastapi import FastAPI
import fastapi
from mcp.server.fastmcp import FastMCP
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
    return await repo.add_interview_session(record)


@mcp.tool(name="get_interview_sessions")
async def get_interview_sessions() -> list[InterviewSessionModel]:
    """Gets a list of interview sessions from database."""
    return await repo.get_all_interview_sessions()


@mcp.tool(name="get_interview_session")
async def get_interview_session(id: UUID) -> InterviewSessionModel | None:
    """Gets an interview session from the database by ID."""
    return await repo.get_interview_session(id)


@mcp.tool(name="update_interview_session")
async def update_interview_session(record: InterviewSessionModel) -> InterviewSessionModel | None:
    """Updates an interview session in the database."""
    return await repo.update_interview_session(record)


@mcp.tool(name="complete_interview_session")
async def complete_interview_session(id: UUID) -> InterviewSessionModel | None:
    """Completes an interview session in the database."""
    return await repo.complete_interview_session(id)
    

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting interview-data service")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with mcp.session_manager.run():
        yield

app = FastAPI(title="interview-data-mcp", lifespan=lifespan)


@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"


app.mount("/interview-data", mcp.streamable_http_app())