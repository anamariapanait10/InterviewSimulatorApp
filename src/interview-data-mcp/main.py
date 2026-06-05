from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from uuid import UUID

import fastapi
import httpx
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from models import (
    InterviewSessionModel,
    RuntimeCodingEventRequest,
    RuntimeCodingMessageRequest,
    RuntimeCodingProblemRequest,
    RuntimeCompleteSessionRequest,
    RuntimeDecisionTraceRequest,
    RuntimeFinalEvaluationRequest,
    RuntimeHandoffRequest,
    RuntimePromptRequest,
    RuntimeSessionRecordRequest,
    RuntimeSessionTurnRequest,
    RuntimeSetActiveAgentRequest,
    RuntimeStageTransitionRequest,
    RuntimeSupportRequest,
)

logger = logging.getLogger("interviewdata")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

mcp = FastMCP("InterviewData", stateless_http=True, json_response=True)
BACKEND_BASE_URL = (
    os.getenv("BACKEND_URL")
    or os.getenv("BACKEND_HTTP")
    or os.getenv("BACKEND_HTTPS")
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


@mcp.tool(name="get_runtime_session")
async def get_runtime_session(session_id: UUID) -> InterviewSessionModel | None:
    data = await _get_json(f"/api/interview-data/runtime/sessions/{session_id}")
    if data is None:
        return None
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="create_runtime_session")
async def create_runtime_session(record: InterviewSessionModel) -> InterviewSessionModel:
    data = await _post_json(
        "/api/interview-data/runtime/sessions",
        RuntimeSessionRecordRequest(record=record).model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="append_turn")
async def append_turn(session_id: UUID, turn: RuntimeSessionTurnRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/turns",
        turn.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="set_active_agent")
async def set_active_agent(session_id: UUID, payload: RuntimeSetActiveAgentRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/active-agent",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="record_handoff")
async def record_handoff(session_id: UUID, payload: RuntimeHandoffRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/handoffs",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="append_decision_trace")
async def append_decision_trace(session_id: UUID, payload: RuntimeDecisionTraceRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/decision-trace",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="transition_stage")
async def transition_stage(session_id: UUID, payload: RuntimeStageTransitionRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/stage",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="save_stage_prompt")
async def save_stage_prompt(session_id: UUID, payload: RuntimePromptRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/prompt",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="save_support_response")
async def save_support_response(session_id: UUID, payload: RuntimeSupportRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/support",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="save_coding_problem")
async def save_coding_problem(session_id: UUID, payload: RuntimeCodingProblemRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/coding/problem",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="append_coding_event")
async def append_coding_event(session_id: UUID, payload: RuntimeCodingEventRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/coding/events",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="append_coding_message")
async def append_coding_message(session_id: UUID, payload: RuntimeCodingMessageRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/coding/messages",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="save_final_evaluation")
async def save_final_evaluation(session_id: UUID, payload: RuntimeFinalEvaluationRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/evaluation",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@mcp.tool(name="complete_session")
async def complete_session(session_id: UUID, payload: RuntimeCompleteSessionRequest) -> InterviewSessionModel:
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/complete",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting interview-data service")
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="interview-data-mcp", lifespan=lifespan)


@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    return "Healthy"


@app.get("/runtime/sessions/{session_id}", response_model=InterviewSessionModel | None)
async def http_get_runtime_session(session_id: UUID):
    data = await _get_json(f"/api/interview-data/runtime/sessions/{session_id}")
    if data is None:
        return None
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions", response_model=InterviewSessionModel)
async def http_create_runtime_session(payload: RuntimeSessionRecordRequest):
    data = await _post_json("/api/interview-data/runtime/sessions", payload.model_dump(mode="json"))
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/turns", response_model=InterviewSessionModel)
async def http_append_turn(session_id: UUID, payload: RuntimeSessionTurnRequest):
    data = await _post_json(f"/api/interview-data/runtime/sessions/{session_id}/turns", payload.model_dump(mode="json"))
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/active-agent", response_model=InterviewSessionModel)
async def http_set_active_agent(session_id: UUID, payload: RuntimeSetActiveAgentRequest):
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/active-agent",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/handoffs", response_model=InterviewSessionModel)
async def http_record_handoff(session_id: UUID, payload: RuntimeHandoffRequest):
    data = await _post_json(f"/api/interview-data/runtime/sessions/{session_id}/handoffs", payload.model_dump(mode="json"))
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/decision-trace", response_model=InterviewSessionModel)
async def http_append_decision_trace(session_id: UUID, payload: RuntimeDecisionTraceRequest):
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/decision-trace",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/stage", response_model=InterviewSessionModel)
async def http_transition_stage(session_id: UUID, payload: RuntimeStageTransitionRequest):
    data = await _post_json(f"/api/interview-data/runtime/sessions/{session_id}/stage", payload.model_dump(mode="json"))
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/prompt", response_model=InterviewSessionModel)
async def http_save_prompt(session_id: UUID, payload: RuntimePromptRequest):
    data = await _post_json(f"/api/interview-data/runtime/sessions/{session_id}/prompt", payload.model_dump(mode="json"))
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/support", response_model=InterviewSessionModel)
async def http_save_support(session_id: UUID, payload: RuntimeSupportRequest):
    data = await _post_json(f"/api/interview-data/runtime/sessions/{session_id}/support", payload.model_dump(mode="json"))
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/coding/problem", response_model=InterviewSessionModel)
async def http_save_coding_problem(session_id: UUID, payload: RuntimeCodingProblemRequest):
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/coding/problem",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/coding/events", response_model=InterviewSessionModel)
async def http_append_coding_event(session_id: UUID, payload: RuntimeCodingEventRequest):
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/coding/events",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/coding/messages", response_model=InterviewSessionModel)
async def http_append_coding_message(session_id: UUID, payload: RuntimeCodingMessageRequest):
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/coding/messages",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/evaluation", response_model=InterviewSessionModel)
async def http_save_evaluation(session_id: UUID, payload: RuntimeFinalEvaluationRequest):
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/evaluation",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


@app.post("/runtime/sessions/{session_id}/complete", response_model=InterviewSessionModel)
async def http_complete_session(session_id: UUID, payload: RuntimeCompleteSessionRequest):
    data = await _post_json(
        f"/api/interview-data/runtime/sessions/{session_id}/complete",
        payload.model_dump(mode="json"),
    )
    return InterviewSessionModel.model_validate(data)


app.mount("/interview-data", mcp.streamable_http_app())
