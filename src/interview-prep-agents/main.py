from __future__ import annotations

from typing import Any, Literal

import fastapi
import fastapi.responses
from fastapi import FastAPI
from pydantic import BaseModel, Field

from upload_routes import router as upload_router
from workflow import handle_orchestrator_action


class OrchestratorActionRequest(BaseModel):
    action: Literal[
        "start_session",
        "submit_turn",
        "skip_turn",
        "request_help",
        "voice_turn",
        "finalize_session",
        "resume_stage",
    ]
    session_id: str = Field(min_length=1)
    user_input: str = ""
    help_kind: Literal["hint", "model_answer"] | None = None
    recent_client_events: list[dict[str, Any]] = Field(default_factory=list)
    coding_payload: dict[str, Any] = Field(default_factory=dict)
    ui_context: dict[str, Any] = Field(default_factory=dict)


class OrchestratorActionResponse(BaseModel):
    stage: str
    active_agent: str | None = None
    handoff: dict[str, Any] | None = None
    interviewer_output: str | None = None
    next_prompt: dict[str, Any] | None = None
    ui_patch: dict[str, Any] = Field(default_factory=dict)
    decision_trace_entry: dict[str, Any] | None = None
    is_stage_complete: bool = False
    is_interview_complete: bool = False
    session: dict[str, Any]
    final_report: dict[str, Any] | None = None
    support_content: str | None = None


app = FastAPI(title="Interview Coach Agent")
app.include_router(upload_router)


@app.post("/orchestrator/act", response_model=OrchestratorActionResponse)
async def orchestrator_act(payload: OrchestratorActionRequest):
    result = await handle_orchestrator_action(
        action=payload.action,
        session_id=payload.session_id,
        user_input=payload.user_input,
        help_kind=payload.help_kind,
        recent_client_events=payload.recent_client_events,
        coding_payload=payload.coding_payload,
        ui_context=payload.ui_context,
    )
    return OrchestratorActionResponse.model_validate(result)


@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    return "Healthy"
