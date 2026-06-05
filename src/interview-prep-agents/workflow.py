from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from agents import Agent, Runner
from agents.handoffs import handoff
from pydantic import BaseModel, Field

from runtime_store_client import get_json, post_json


OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
logger = logging.getLogger("interview-prep-agents.workflow")
BACKEND_BASE_URL = (
    os.getenv("BACKEND_URL")
    or os.getenv("BACKEND_HTTP")
    or "http://127.0.0.1:8002"
).rstrip("/")


class StageTurnOutput(BaseModel):
    prompt: str
    prompt_kind: Literal["question", "followup"]
    stage_complete: bool = False
    transition_reason: str | None = None
    transition_message: str | None = None


class SupportOutput(BaseModel):
    content: str
    support_mode: Literal["hint", "model_answer"]


class CodingOutput(BaseModel):
    coding_mode: Literal["select_problem", "clarify", "followup", "intervene"]
    reply: str = ""
    selected_problem_id: str | None = None
    selection_rationale: str | None = None


class FinalEvaluationOutput(BaseModel):
    behavioral_score: int = Field(ge=1, le=100)
    technical_score: int = Field(ge=1, le=100)
    coding_score: int = Field(ge=1, le=100)
    communication_score: int = Field(ge=1, le=100)
    overall_score: int = Field(ge=1, le=100)
    behavioral_feedback: str
    technical_feedback: str
    coding_feedback: str
    communication_feedback: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    hire_recommendation: str
    recommendation: str


@dataclass
class OrchestrationContext:
    action: str
    session: dict[str, Any]
    user_input: str = ""
    help_kind: str | None = None
    coding_payload: dict[str, Any] = field(default_factory=dict)
    ui_context: dict[str, Any] = field(default_factory=dict)
    problem_candidates: list[dict[str, Any]] = field(default_factory=list)
    handoff_log: list[dict[str, str]] = field(default_factory=list)


def _strip(text: str | None) -> str:
    return (text or "").strip()


def _current_stage(session: dict[str, Any]) -> str:
    return str(session.get("current_stage") or "behavioral")


def _behavioral_target(session: dict[str, Any]) -> int:
    blueprint = session.get("interview_blueprint") or {}
    return int(blueprint.get("behavioral_target_questions") or 2)


def _technical_target(session: dict[str, Any]) -> int:
    blueprint = session.get("interview_blueprint") or {}
    return int(blueprint.get("technical_target_questions") or 2)


def _question_counts(session: dict[str, Any]) -> tuple[int, int]:
    questions = session.get("questions") or []
    behavioral = sum(1 for q in questions if q.get("category") == "behavioral")
    technical = sum(1 for q in questions if q.get("category") == "technical")
    return behavioral, technical


def _stage_target_reached(session: dict[str, Any], stage: str) -> bool:
    behavioral_count, technical_count = _question_counts(session)
    if stage == "behavioral":
        return behavioral_count >= _behavioral_target(session)
    if stage == "technical":
        return technical_count >= _technical_target(session)
    return False


def _recent_turns_text(session: dict[str, Any], stage: str, limit: int = 8) -> str:
    turns = [
        turn
        for turn in (session.get("turn_log") or [])
        if turn.get("stage") == stage
    ]
    if not turns:
        return "No prior turns yet."
    lines = [
        f"{turn.get('role', 'system').title()} [{turn.get('kind', 'message')}]: {str(turn.get('content') or '').strip()}"
        for turn in turns[-limit:]
        if str(turn.get("content") or "").strip()
    ]
    return "\n".join(lines) if lines else "No prior turns yet."


def _current_question(session: dict[str, Any]) -> dict[str, Any] | None:
    current_index = int(session.get("current_question_index") or 0)
    questions = session.get("questions") or []
    if 0 <= current_index < len(questions):
        return questions[current_index]
    return None


def _coding_mode_for_request(context: OrchestrationContext) -> str:
    if _current_stage(context.session) != "coding":
        return "select_problem"

    coding_round = context.session.get("coding_round") or {}
    if not coding_round.get("problem"):
        return "select_problem"

    recent_events = context.coding_payload.get("recent_client_events") or []
    if any(event.get("type") == "clarification_asked" for event in recent_events):
        return "clarify"
    if any(event.get("type") == "candidate_pause" for event in recent_events):
        return "intervene"

    transcript = _strip(context.coding_payload.get("transcript_recent"))
    if transcript:
        lowered = transcript.lower()
        if any(token in lowered for token in ("time complexity", "space complexity", "edge case", "stuck", "blocked")):
            return "intervene"
        if any(token in lowered for token in ("clarify", "constraint", "problem statement", "explain the problem", "help me understand")):
            return "clarify"
        return "followup"

    code = _strip(context.coding_payload.get("code"))
    if code:
        return "followup"
    return "intervene"


def _build_orchestrator_prompt(context: OrchestrationContext) -> str:
    session = context.session
    stage = _current_stage(session)
    behavioral_count, technical_count = _question_counts(session)
    current_question = _current_question(session)
    current_question_text = str(current_question.get("prompt") or "") if current_question else "none"
    return f"""
You are the interview orchestrator.

Current action: {context.action}
Current stage: {stage}
Current active question: {current_question_text}
Help mode: {context.help_kind or "none"}
Latest user input:
{context.user_input or "none"}

Behavioral questions asked so far: {behavioral_count}/{_behavioral_target(session)}
Technical questions asked so far: {technical_count}/{_technical_target(session)}

Rules:
- Never answer directly.
- Always hand off to exactly one specialist.
- Use the behavioral interviewer for behavioral-stage questioning.
- Use the technical interviewer for technical-stage questioning.
- Use the support agent only for explicit hint/model_answer requests.
- Use the coding agent for coding problem selection, clarification, follow-up, and intervention turns.
- Use the final evaluator only when the interview is being finalized.
""".strip()


def _build_behavioral_instructions(context: OrchestrationContext) -> str:
    session = context.session
    blueprint = session.get("interview_blueprint") or {}
    return f"""
You are the behavioral interviewer for a realistic mock interview.

Role title: {session.get("role_title") or "Target role"}
Target company: {session.get("company_name") or session.get("target_company") or "not specified"}
Behavioral goal: {blueprint.get("behavioral_goal") or "Assess ownership, impact, and communication."}

Resume:
{session.get("resume_text") or ""}

Job description:
{session.get("job_description_text") or ""}

Company-specific context:
{session.get("company_context") or "No additional company context provided."}

Recent behavioral turns:
{_recent_turns_text(session, "behavioral")}

Latest candidate input:
{context.user_input or "No candidate input yet. Start the stage with a strong first question."}

Return structured output only.
Rules:
- Ask one concise question or follow-up at a time.
- Focus on impact, ownership, tradeoffs, prioritization, communication, and leadership.
- If enough evidence has been collected for the behavioral stage, set stage_complete to true.
- Only mark stage_complete when you are ready for the interview to move to the technical stage.
""".strip()


def _build_technical_instructions(context: OrchestrationContext) -> str:
    session = context.session
    blueprint = session.get("interview_blueprint") or {}
    return f"""
You are the technical interviewer for a realistic mock interview.

Role title: {session.get("role_title") or "Target role"}
Target company: {session.get("company_name") or session.get("target_company") or "not specified"}
Technical goal: {blueprint.get("technical_goal") or "Assess technical depth, tradeoffs, and debugging."}

Resume:
{session.get("resume_text") or ""}

Job description:
{session.get("job_description_text") or ""}

Company-specific context:
{session.get("company_context") or "No additional company context provided."}

Recent technical turns:
{_recent_turns_text(session, "technical")}

Latest candidate input:
{context.user_input or "No candidate input yet. Start the stage with a strong technical question."}

Return structured output only.
Rules:
- Ask one concise technical question or follow-up at a time.
- Focus on architecture, design, tradeoffs, debugging, and problem-solving depth.
- If enough evidence has been collected for the technical stage, set stage_complete to true.
- Only mark stage_complete when you are ready for the interview to move to the coding stage.
""".strip()


def _build_support_instructions(context: OrchestrationContext) -> str:
    session = context.session
    stage = _current_stage(session)
    question = _current_question(session)
    question_text = question.get("prompt") if question else (
        (session.get("coding_round") or {}).get("problem", {}) or {}
    )
    question_block = question_text if isinstance(question_text, str) else str(question_text)
    return f"""
You are the interview support agent.

Support mode: {context.help_kind or "hint"}
Current stage: {stage}
Current prompt:
{question_block}

Resume:
{session.get("resume_text") or ""}

Job description:
{session.get("job_description_text") or ""}

Company context:
{session.get("company_context") or "No additional company context provided."}

Rules:
- For hint, be short and directional without giving the full answer.
- For model_answer, provide a polished answer that fits the current stage.
- Stay tightly scoped to the current active prompt.
""".strip()


async def _fetch_problem_candidates(session: dict[str, Any]) -> list[dict[str, Any]]:
    query = "\n".join(
        part
        for part in [
            str(session.get("target_company") or session.get("company_name") or ""),
            str(session.get("role_title") or ""),
            str(session.get("coding_difficulty") or ""),
            str(session.get("company_context") or "")[:1800],
            str(session.get("job_description_text") or "")[:1800],
        ]
        if part
    ).strip()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BACKEND_BASE_URL}/api/internal/problem-catalog/search",
            json={"query": query, "top_k": 5},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError("Problem catalog search returned invalid payload")
        return data


async def _fetch_problem(problem_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BACKEND_BASE_URL}/api/internal/coding-problems/{problem_id}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Coding problem lookup returned invalid payload")
        return data


async def _fetch_company_context(session: dict[str, Any], question_prompt: str | None = None) -> str | None:
    company_id = session.get("company_id")
    if not company_id:
        return None
    query_parts = [
        str(session.get("role_title") or ""),
        str(session.get("job_description_text") or "")[:1800],
    ]
    if question_prompt:
        query_parts.append(question_prompt)
    query = "\n\n".join(part for part in query_parts if part).strip()
    if not query:
        return None
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BACKEND_BASE_URL}/api/companies/{company_id}/rag/search",
            json={"query": query, "top_k": 4},
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            return None
        blocks = [str(item.get("content") or "").strip() for item in rows if str(item.get("content") or "").strip()]
        return "\n\n".join(blocks) if blocks else None


async def _maybe_refresh_company_context(session: dict[str, Any], question_prompt: str | None = None) -> str | None:
    current = _strip(session.get("company_context"))
    if current:
        return current
    return await _fetch_company_context(session, question_prompt)


def _build_coding_instructions(context: OrchestrationContext) -> str:
    session = context.session
    coding_round = session.get("coding_round") or {}
    coding_mode = _coding_mode_for_request(context)
    problem = coding_round.get("problem") or {}
    candidates = context.problem_candidates if coding_mode == "select_problem" else []

    candidate_block = "\n".join(
        f"- {row.get('metadata', {}).get('problem_id')}: {row.get('metadata', {}).get('title')} | "
        f"{row.get('metadata', {}).get('company')} | {row.get('metadata', {}).get('difficulty')} | "
        f"{row.get('metadata', {}).get('expected_topics')} | {row.get('metadata', {}).get('style_tags')}"
        for row in candidates
    ) or "No candidates provided."

    recent_events = context.coding_payload.get("recent_client_events") or []
    recent_event_types = ", ".join(str(item.get("type") or "") for item in recent_events if item.get("type")) or "none"
    return f"""
You are the coding specialist for a realistic coding interview.

Coding mode: {coding_mode}
Role title: {session.get("role_title") or "Target role"}
Target company: {session.get("target_company") or session.get("company_name") or "not specified"}
Difficulty: {session.get("coding_difficulty") or "medium"}
Interviewer mode: {session.get("interviewer_mode") or "neutral"}

Company context:
{session.get("company_context") or "No additional company context provided."}

Current problem:
{problem.get('title') or 'No problem selected yet.'}
{problem.get('prompt') or ''}

Problem constraints:
{chr(10).join(f"- {constraint}" for constraint in (problem.get('constraints') or []))}

Recent coding conversation:
{_recent_turns_text(session, "coding")}

Latest candidate transcript:
{context.coding_payload.get("transcript_recent") or context.user_input or "none"}

Recent event types:
{recent_event_types}

Current code excerpt:
{str(context.coding_payload.get("code") or coding_round.get("current_code") or "")[-1800:]}

Problem candidates for selection:
{candidate_block}

Rules:
- In select_problem mode, choose exactly one problem id from the provided candidates and explain why.
- In clarify mode, answer only the prompt/constraints/examples question without giving the full solution.
- In followup mode, respond briefly and naturally as the interviewer.
- In intervene mode, ask a short pointed question about the candidate's current gap.
- Never invent a new problem outside the catalog.
""".strip()


def _build_final_evaluator_instructions(context: OrchestrationContext) -> str:
    session = context.session
    coding_round = session.get("coding_round") or {}
    return f"""
You are the final evaluator for a mock interview.

Role title: {session.get("role_title") or "Target role"}
Target company: {session.get("target_company") or session.get("company_name") or "not specified"}

Resume:
{session.get("resume_text") or ""}

Job description:
{session.get("job_description_text") or ""}

Behavioral and technical turns:
{_recent_turns_text(session, "behavioral", limit=20)}

{_recent_turns_text(session, "technical", limit=20)}

Coding conversation:
{_recent_turns_text(session, "coding", limit=24)}

Coding code excerpt:
{str(coding_round.get("current_code") or "")[-5000:]}

Rules:
- Produce stage-specific feedback for behavioral, technical, coding, and communication.
- Score each section fairly and pragmatically.
- Return one coherent final recommendation.
""".strip()


def _record_handoff(context, from_agent: str, to_agent: str, reason: str) -> None:
    context.context.handoff_log.append(
        {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "stage": _current_stage(context.context.session),
            "reason": reason,
        }
    )


def _handoff_enabled(expected_stage: str | None = None, action: str | None = None):
    def _inner(run_context, _agent) -> bool:
        ctx: OrchestrationContext = run_context.context
        if action and ctx.action != action:
            return False
        if expected_stage and _current_stage(ctx.session) != expected_stage:
            return False
        return True

    return _inner


def _build_agents(context: OrchestrationContext) -> Agent:
    behavioral_agent = Agent(
        name="behavioral_interviewer_agent",
        handoff_description="Asks and follows up on behavioral interview questions.",
        instructions=lambda run_context, _agent: _build_behavioral_instructions(run_context.context),
        model=OPENAI_MODEL,
        output_type=StageTurnOutput,
    )
    technical_agent = Agent(
        name="technical_interviewer_agent",
        handoff_description="Asks and follows up on technical interview questions before the coding round.",
        instructions=lambda run_context, _agent: _build_technical_instructions(run_context.context),
        model=OPENAI_MODEL,
        output_type=StageTurnOutput,
    )
    support_agent = Agent(
        name="interview_support_agent",
        handoff_description="Generates hints and model answers for the current interview step.",
        instructions=lambda run_context, _agent: _build_support_instructions(run_context.context),
        model=OPENAI_MODEL,
        output_type=SupportOutput,
    )
    coding_agent = Agent(
        name="coding_agent",
        handoff_description="Selects coding problems and handles coding clarification, follow-up, and intervention turns.",
        instructions=lambda run_context, _agent: _build_coding_instructions(run_context.context),
        model=OPENAI_MODEL,
        output_type=CodingOutput,
    )
    final_evaluator_agent = Agent(
        name="final_evaluator_agent",
        handoff_description="Evaluates the full interview and returns the final report.",
        instructions=lambda run_context, _agent: _build_final_evaluator_instructions(run_context.context),
        model=OPENAI_MODEL,
        output_type=FinalEvaluationOutput,
    )

    orchestrator = Agent(
        name="interview_orchestrator_agent",
        instructions=lambda run_context, _agent: _build_orchestrator_prompt(run_context.context),
        model=OPENAI_MODEL,
        handoffs=[
            handoff(
                behavioral_agent,
                on_handoff=lambda run_context: _record_handoff(
                    run_context,
                    "interview_orchestrator_agent",
                    "behavioral_interviewer_agent",
                    "behavioral stage routing",
                ),
                is_enabled=lambda run_context, _agent: _current_stage(run_context.context.session) == "behavioral"
                and run_context.context.action in {"start_session", "submit_turn", "skip_turn", "voice_turn", "resume_stage"},
            ),
            handoff(
                technical_agent,
                on_handoff=lambda run_context: _record_handoff(
                    run_context,
                    "interview_orchestrator_agent",
                    "technical_interviewer_agent",
                    "technical stage routing",
                ),
                is_enabled=lambda run_context, _agent: _current_stage(run_context.context.session) == "technical"
                and run_context.context.action in {"submit_turn", "skip_turn", "voice_turn", "resume_stage"},
            ),
            handoff(
                support_agent,
                on_handoff=lambda run_context: _record_handoff(
                    run_context,
                    "interview_orchestrator_agent",
                    "interview_support_agent",
                    f"support request: {run_context.context.help_kind or 'hint'}",
                ),
                is_enabled=lambda run_context, _agent: run_context.context.action == "request_help",
            ),
            handoff(
                coding_agent,
                on_handoff=lambda run_context: _record_handoff(
                    run_context,
                    "interview_orchestrator_agent",
                    "coding_agent",
                    f"coding mode: {_coding_mode_for_request(run_context.context)}",
                ),
                is_enabled=lambda run_context, _agent: _current_stage(run_context.context.session) == "coding"
                and run_context.context.action in {"voice_turn", "resume_stage"},
            ),
            handoff(
                final_evaluator_agent,
                on_handoff=lambda run_context: _record_handoff(
                    run_context,
                    "interview_orchestrator_agent",
                    "final_evaluator_agent",
                    "final evaluation routing",
                ),
                is_enabled=lambda run_context, _agent: run_context.context.action == "finalize_session",
            ),
        ],
    )
    return orchestrator


def _build_blueprint(session: dict[str, Any]) -> dict[str, Any]:
    length = str(session.get("interview_length") or "medium")
    counts = {
        "short": (2, 2),
        "medium": (4, 4),
        "long": (6, 6),
    }.get(length, (4, 4))
    role_title = _strip(session.get("role_title")) or "Target role"
    target_company = _strip(session.get("target_company")) or _strip(session.get("company_name")) or None
    return {
        "role_title": role_title,
        "behavioral_goal": "Assess ownership, communication, leadership, and impact with concrete examples.",
        "technical_goal": "Assess technical depth, design tradeoffs, debugging, and reasoning quality before coding.",
        "behavioral_target_questions": counts[0],
        "technical_target_questions": counts[1],
        "target_company": target_company,
        "focus_areas": [role_title, target_company] if target_company else [role_title],
    }


async def _run_specialist(context: OrchestrationContext) -> Any:
    if _current_stage(context.session) == "coding":
        coding_round = context.session.get("coding_round") or {}
        if not coding_round.get("problem") and not context.problem_candidates:
            context.problem_candidates = await _fetch_problem_candidates(context.session)
    orchestrator = _build_agents(context)
    result = await Runner.run(orchestrator, input="Route this turn to the right specialist.", context=context)
    if not context.handoff_log:
        raise RuntimeError("The orchestrator did not perform a specialist handoff")
    return result.final_output


def _build_candidate_turn(session: dict[str, Any], content: str, stage: str, kind: str = "answer") -> dict[str, Any]:
    return {
        "stage": stage,
        "role": "candidate",
        "kind": kind,
        "content": content.strip(),
        "metadata": {},
    }


def _build_interviewer_turn(
    stage: str,
    content: str,
    kind: str,
    agent_name: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "role": "interviewer",
        "agent_name": agent_name,
        "kind": kind,
        "content": content.strip(),
        "metadata": metadata or {},
    }


def _coding_candidate_turn_kind(source_event_type: str | None) -> str:
    if source_event_type == "clarification_asked":
        return "clarification"
    return "answer"


async def _store_get_session(session_id: str) -> dict[str, Any]:
    payload = await get_json(f"/runtime/sessions/{session_id}")
    if payload is None or not isinstance(payload, dict):
        raise RuntimeError("Runtime session not found")
    return payload


async def _store_append_turn(session_id: str, turn: dict[str, Any]) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/turns", {"turn": turn})


async def _store_set_active_agent(session_id: str, active_agent: str) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/active-agent", {"active_agent": active_agent})


async def _store_record_handoff(session_id: str, handoff_entry: dict[str, Any]) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/handoffs", {"handoff": handoff_entry})


async def _store_append_decision_trace(session_id: str, decision_entry: dict[str, Any]) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/decision-trace", {"decision": decision_entry})


async def _store_transition_stage(session_id: str, stage: str, reason: str, prompt: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"stage": stage, "reason": reason}
    if prompt is not None:
        payload["prompt"] = prompt
    return await post_json(f"/runtime/sessions/{session_id}/stage", payload)


async def _store_save_prompt(session_id: str, prompt: dict[str, Any]) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/prompt", {"prompt": prompt})


async def _store_save_support(session_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/support", {"entry": entry})


async def _store_save_coding_problem(session_id: str, coding_round: dict[str, Any]) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/coding/problem", {"coding_round": coding_round})


async def _store_append_coding_event(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/coding/events", payload)


async def _store_append_coding_message(session_id: str, turn: dict[str, Any]) -> dict[str, Any]:
    return await post_json(f"/runtime/sessions/{session_id}/coding/messages", {"turn": turn})


async def _store_save_final_evaluation(session_id: str, evaluation: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    return await post_json(
        f"/runtime/sessions/{session_id}/evaluation",
        {"evaluation": evaluation, "report": report},
    )


async def _store_complete_session(session_id: str, report: dict[str, Any], evaluation: dict[str, Any] | None) -> dict[str, Any]:
    return await post_json(
        f"/runtime/sessions/{session_id}/complete",
        {"report": report, "evaluation": evaluation},
    )


async def _bootstrap_session(session_id: str) -> dict[str, Any]:
    session = await _store_get_session(session_id)
    if session.get("interview_blueprint") is None:
        blueprint = _build_blueprint(session)
        session = await post_json(
            "/runtime/sessions",
            {"record": {**session, "interview_blueprint": blueprint, "role_title": blueprint["role_title"]}},
        )
    return session


def _build_evaluation_and_report(output: FinalEvaluationOutput, session: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    coding_evaluation = None
    coding_round = session.get("coding_round") or {}
    if coding_round.get("problem"):
        coding_evaluation = {
            "communication": max(1, min(10, round(output.communication_score / 10))),
            "problem_solving": max(1, min(10, round(output.coding_score / 10))),
            "coding": max(1, min(10, round(output.coding_score / 10))),
            "complexity_analysis": max(1, min(10, round(output.technical_score / 10))),
            "debugging": max(1, min(10, round(output.technical_score / 10))),
            "edge_cases": max(1, min(10, round(output.coding_score / 10))),
            "overall_score": output.coding_score,
            "hire_recommendation": output.hire_recommendation,
            "summary": output.coding_feedback,
            "strengths": output.strengths[:3],
            "concerns": output.improvements[:3],
        }

    evaluation = output.model_dump(mode="json")
    report = {
        "summary": output.summary,
        "strengths": output.strengths,
        "improvements": output.improvements,
        "behavioral_feedback": output.behavioral_feedback,
        "technical_feedback": output.technical_feedback,
        "communication_feedback": output.communication_feedback,
        "recommendation": output.recommendation,
        "question_feedback": [],
        "coding_feedback": output.coding_feedback,
        "coding_evaluation": coding_evaluation,
        "hire_recommendation": output.hire_recommendation,
    }
    return evaluation, report


async def _resume_stage(session: dict[str, Any]) -> dict[str, Any]:
    context = OrchestrationContext(action="resume_stage", session=session)
    specialist_output = await _run_specialist(context)
    session_id = str(session["id"])
    latest_handoff = context.handoff_log[-1]

    await _store_set_active_agent(session_id, latest_handoff["to_agent"])
    await _store_record_handoff(session_id, latest_handoff)

    if isinstance(specialist_output, StageTurnOutput):
        turn = _build_interviewer_turn(
            _current_stage(session),
            specialist_output.prompt,
            specialist_output.prompt_kind,
            latest_handoff["to_agent"],
        )
        session = await _store_append_turn(session_id, turn)
        await _store_save_prompt(session_id, turn)
        await _store_append_decision_trace(
            session_id,
            {
                "active_agent": latest_handoff["to_agent"],
                "decision_type": "prompt",
                "summary": f"Asked a {specialist_output.prompt_kind} during {_current_stage(session)} stage.",
                "stage": _current_stage(session),
            },
        )
        return await _store_get_session(session_id)

    if isinstance(specialist_output, CodingOutput):
        candidates = await _fetch_problem_candidates(session)
        selected_id = specialist_output.selected_problem_id or (
            candidates[0].get("metadata", {}).get("problem_id") if candidates else None
        )
        if not selected_id:
            raise RuntimeError("Coding agent did not select a valid problem")
        selected_problem = await _fetch_problem(selected_id)
        coding_round = {
            "enabled": True,
            "target_company": session.get("target_company"),
            "matched_company": selected_problem.get("company"),
            "selection_strategy": "rag_match",
            "interviewer_mode": session.get("interviewer_mode") or "neutral",
            "difficulty": session.get("coding_difficulty") or "medium",
            "problem": selected_problem,
            "selection_rationale": specialist_output.selection_rationale,
            "language": session.get("preferred_language") or "typescript",
            "editor_mode": "plain" if (session.get("coding_difficulty") or "medium") == "hard" else "monaco",
            "current_code": (selected_problem.get("starter_code") or {}).get(session.get("preferred_language") or "typescript", ""),
            "transcript": "",
            "interviewer_prompt": f"Conduct a concise {session.get('interviewer_mode') or 'neutral'} coding interview.",
            "current_mode": "select_problem",
            "event_log": [],
            "conversation": [],
            "interventions": [],
            "cooldown_seconds": 40,
            "last_intervention_at": None,
            "latest_reason": None,
            "evaluation": None,
            "started_at": session.get("updated_at"),
            "completed_at": None,
        }
        session = await _store_save_coding_problem(session_id, coding_round)
        opening_turn = {
            "stage": "coding",
            "role": "interviewer",
            "agent_name": latest_handoff["to_agent"],
            "kind": "coding_reply",
            "content": specialist_output.reply or "Let's move into the coding round. Talk me through your approach as you work.",
            "metadata": {"coding_mode": "select_problem"},
        }
        session = await _store_append_turn(session_id, opening_turn)
        session = await _store_append_coding_message(
            session_id,
            {
                "role": "interviewer",
                "content": opening_turn["content"],
                "kind": "opening",
                "source_event_type": "transition",
                "severity": None,
            },
        )
        await _store_append_decision_trace(
            session_id,
            {
                "active_agent": latest_handoff["to_agent"],
                "decision_type": "coding_problem_selected",
                "summary": specialist_output.selection_rationale or f"Selected {selected_problem.get('title')}.",
                "stage": "coding",
            },
        )
        return await _store_get_session(session_id)

    raise RuntimeError("Unsupported specialist output during stage resume")


async def handle_orchestrator_action(
    *,
    action: str,
    session_id: str,
    user_input: str = "",
    help_kind: str | None = None,
    recent_client_events: list[dict[str, Any]] | None = None,
    coding_payload: dict[str, Any] | None = None,
    ui_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = await _bootstrap_session(session_id)
    stage = _current_stage(session)
    coding_payload = coding_payload or {}
    if recent_client_events:
        coding_payload = {**coding_payload, "recent_client_events": recent_client_events}

    if action == "start_session":
        if stage != "behavioral":
            session = await _store_transition_stage(session_id, "behavioral", "start interview")
        session = await _resume_stage(session)
        return {
            "stage": session.get("current_stage"),
            "active_agent": session.get("active_agent"),
            "handoff": session.get("handoff_history", [])[-1] if session.get("handoff_history") else None,
            "interviewer_output": (session.get("current_prompt") or {}).get("content"),
            "next_prompt": session.get("current_prompt"),
            "ui_patch": {"show_coding_round": False},
            "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
            "is_stage_complete": False,
            "is_interview_complete": False,
            "session": session,
            "final_report": None,
        }

    if action in {"submit_turn", "skip_turn", "voice_turn"} and stage in {"behavioral", "technical"}:
        turn_text = user_input.strip() or ("[Skipped by candidate]" if action == "skip_turn" else "")
        if turn_text:
            session = await _store_append_turn(session_id, _build_candidate_turn(session, turn_text, stage))

        if _stage_target_reached(session, stage):
            next_stage = "technical" if stage == "behavioral" else "coding"
            await _store_append_decision_trace(
                session_id,
                {
                    "active_agent": "interview_orchestrator_agent",
                    "decision_type": "stage_transition",
                    "summary": f"Reached the configured {stage} question target; moving to {next_stage}.",
                    "stage": stage,
                },
            )
            session = await _store_transition_stage(
                session_id,
                next_stage,
                f"Reached configured {stage} question target",
            )
            session = await _resume_stage(session)
            return {
                "stage": session.get("current_stage"),
                "active_agent": session.get("active_agent"),
                "handoff": session.get("handoff_history", [])[-1] if session.get("handoff_history") else None,
                "interviewer_output": (
                    (session.get("current_prompt") or {}).get("content")
                    if session.get("current_stage") != "coding"
                    else (((session.get("coding_round") or {}).get("conversation") or [{}])[-1].get("content"))
                ),
                "next_prompt": session.get("current_prompt"),
                "ui_patch": {"show_coding_round": session.get("current_stage") == "coding"},
                "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
                "is_stage_complete": True,
                "is_interview_complete": False,
                "session": session,
                "final_report": None,
            }

        context = OrchestrationContext(
            action=action,
            session=session,
            user_input=turn_text,
            ui_context=ui_context or {},
        )
        specialist_output = await _run_specialist(context)
        latest_handoff = context.handoff_log[-1]
        await _store_set_active_agent(session_id, latest_handoff["to_agent"])
        await _store_record_handoff(session_id, latest_handoff)

        if not isinstance(specialist_output, StageTurnOutput):
            raise RuntimeError("Expected a stage turn output for a pre-coding interview turn")

        if specialist_output.stage_complete:
            next_stage = "technical" if stage == "behavioral" else "coding"
            session = await _store_transition_stage(
                session_id,
                next_stage,
                specialist_output.transition_reason or f"completed {stage} stage",
            )
            session = await _resume_stage(session)
        else:
            interviewer_turn = _build_interviewer_turn(
                stage,
                specialist_output.prompt,
                specialist_output.prompt_kind,
                latest_handoff["to_agent"],
            )
            session = await _store_append_turn(session_id, interviewer_turn)
            session = await _store_save_prompt(session_id, interviewer_turn)
            await _store_append_decision_trace(
                session_id,
                {
                    "active_agent": latest_handoff["to_agent"],
                    "decision_type": "prompt",
                    "summary": f"Asked a {specialist_output.prompt_kind} during {stage} stage.",
                    "stage": stage,
                },
            )
            session = await _store_get_session(session_id)

        return {
            "stage": session.get("current_stage"),
            "active_agent": session.get("active_agent"),
            "handoff": session.get("handoff_history", [])[-1] if session.get("handoff_history") else None,
            "interviewer_output": (
                (session.get("current_prompt") or {}).get("content")
                if session.get("current_stage") != "coding"
                else (((session.get("coding_round") or {}).get("conversation") or [{}])[-1].get("content"))
            ),
            "next_prompt": session.get("current_prompt"),
            "ui_patch": {"show_coding_round": session.get("current_stage") == "coding"},
            "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
            "is_stage_complete": stage != session.get("current_stage"),
            "is_interview_complete": False,
            "session": session,
            "final_report": None,
        }

    if action == "request_help":
        context = OrchestrationContext(
            action=action,
            session=session,
            help_kind=help_kind or "hint",
            user_input=user_input,
            ui_context=ui_context or {},
        )
        specialist_output = await _run_specialist(context)
        latest_handoff = context.handoff_log[-1]
        await _store_set_active_agent(session_id, latest_handoff["to_agent"])
        await _store_record_handoff(session_id, latest_handoff)
        if not isinstance(specialist_output, SupportOutput):
            raise RuntimeError("Expected support output for help request")
        current_question = _current_question(session)
        support_entry = {
            "mode": specialist_output.support_mode,
            "stage": _current_stage(session),
            "question_id": current_question.get("id") if current_question else None,
            "content": specialist_output.content,
        }
        session = await _store_save_support(session_id, support_entry)
        session = await _store_append_turn(
            session_id,
            {
                "stage": _current_stage(session),
                "role": "interviewer",
                "agent_name": latest_handoff["to_agent"],
                "kind": specialist_output.support_mode,
                "content": specialist_output.content,
                "metadata": {},
            },
        )
        return {
            "stage": session.get("current_stage"),
            "active_agent": session.get("active_agent"),
            "handoff": latest_handoff,
            "interviewer_output": specialist_output.content,
            "next_prompt": session.get("current_prompt"),
            "ui_patch": {},
            "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
            "is_stage_complete": False,
            "is_interview_complete": False,
            "session": session,
            "final_report": None,
            "support_content": specialist_output.content,
        }

    if action in {"voice_turn", "resume_stage"} and _current_stage(session) == "coding":
        if action == "voice_turn":
            recent_events = recent_client_events or []
            for event in recent_events:
                session = await _store_append_coding_event(
                    session_id,
                    {
                        "event": event,
                        "code": coding_payload.get("code") or "",
                        "language": coding_payload.get("language"),
                        "transcript_append": coding_payload.get("transcript_recent") or "",
                    },
                )

            transcript_text = _strip(user_input or coding_payload.get("transcript_recent"))
            latest_event_type = (
                str(recent_events[-1].get("type"))
                if recent_events and recent_events[-1].get("type")
                else None
            )
            if transcript_text:
                candidate_turn = {
                    "stage": "coding",
                    "role": "candidate",
                    "kind": _coding_candidate_turn_kind(latest_event_type),
                    "content": transcript_text,
                    "metadata": {"source_event_type": latest_event_type or "candidate_spoke"},
                }
                session = await _store_append_turn(session_id, candidate_turn)
                session = await _store_append_coding_message(
                    session_id,
                    {
                        "role": "candidate",
                        "content": transcript_text,
                        "kind": "message",
                        "source_event_type": latest_event_type,
                        "severity": None,
                    },
                )

        context = OrchestrationContext(
            action=action,
            session=session,
            user_input=user_input,
            coding_payload=coding_payload,
            ui_context=ui_context or {},
        )
        specialist_output = await _run_specialist(context)
        latest_handoff = context.handoff_log[-1]
        await _store_set_active_agent(session_id, latest_handoff["to_agent"])
        await _store_record_handoff(session_id, latest_handoff)
        if not isinstance(specialist_output, CodingOutput):
            raise RuntimeError("Expected coding output during coding stage")

        message_kind = "intervention" if specialist_output.coding_mode == "intervene" else "coding_reply"
        if specialist_output.reply.strip():
            interviewer_turn = {
                "stage": "coding",
                "role": "interviewer",
                "agent_name": latest_handoff["to_agent"],
                "kind": message_kind,
                "content": specialist_output.reply.strip(),
                "metadata": {"coding_mode": specialist_output.coding_mode},
            }
            session = await _store_append_turn(session_id, interviewer_turn)
            session = await _store_append_coding_message(
                session_id,
                {
                    "role": "interviewer",
                    "content": specialist_output.reply.strip(),
                    "kind": "intervention" if specialist_output.coding_mode == "intervene" else "reply",
                    "source_event_type": specialist_output.coding_mode,
                    "severity": "medium" if specialist_output.coding_mode == "intervene" else None,
                },
            )
        await _store_append_decision_trace(
            session_id,
            {
                "active_agent": latest_handoff["to_agent"],
                "decision_type": specialist_output.coding_mode,
                "summary": specialist_output.selection_rationale or specialist_output.reply or specialist_output.coding_mode,
                "stage": "coding",
            },
        )
        session = await _store_get_session(session_id)
        return {
            "stage": session.get("current_stage"),
            "active_agent": session.get("active_agent"),
            "handoff": latest_handoff,
            "interviewer_output": specialist_output.reply.strip(),
            "next_prompt": None,
            "ui_patch": {"show_coding_round": True},
            "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
            "is_stage_complete": False,
            "is_interview_complete": False,
            "session": session,
            "final_report": None,
        }

    if action == "finalize_session":
        context = OrchestrationContext(
            action=action,
            session=session,
            user_input=user_input,
            coding_payload=coding_payload,
            ui_context=ui_context or {},
        )
        specialist_output = await _run_specialist(context)
        latest_handoff = context.handoff_log[-1]
        await _store_set_active_agent(session_id, latest_handoff["to_agent"])
        await _store_record_handoff(session_id, latest_handoff)
        if not isinstance(specialist_output, FinalEvaluationOutput):
            raise RuntimeError("Expected final evaluation output during interview finalization")
        evaluation, report = _build_evaluation_and_report(specialist_output, session)
        session = await _store_save_final_evaluation(session_id, evaluation, report)
        session = await _store_complete_session(session_id, report, evaluation)
        return {
            "stage": "completed",
            "active_agent": latest_handoff["to_agent"],
            "handoff": latest_handoff,
            "interviewer_output": specialist_output.summary,
            "next_prompt": None,
            "ui_patch": {"show_coding_round": False},
            "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
            "is_stage_complete": True,
            "is_interview_complete": True,
            "session": session,
            "final_report": report,
        }

    raise RuntimeError(f"Unsupported orchestrator action: {action}")
