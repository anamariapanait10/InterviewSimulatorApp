from __future__ import annotations

import logging
import os
from uuid import UUID

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from db import Base, engine
from models import InterviewSessionModel
from repository import InterviewSessionRepository
from contextlib import asynccontextmanager

logger = logging.getLogger("interviewdata")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

repo = InterviewSessionRepository()
mcp = FastMCP("InterviewData")


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


async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # here put code to run on startup
    await startup()
    yield
    # here put code to run on shutdown

app = FastAPI(title="interview-data-mcp", lifespan=lifespan)

# Expose MCP on /mcp
app.mount("/mcp", mcp.streamable_http_app())