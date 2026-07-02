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


class FinalQuestionFeedbackOutput(BaseModel):
    question_id: str
    score: int = Field(ge=1, le=10)
    feedback: str


class FinalEvaluationOutput(BaseModel):
    behavioral_score: int = Field(ge=1, le=100)
    technical_score: int = Field(ge=1, le=100)
    coding_score: int = Field(ge=1, le=100)
    communication_score: int = Field(ge=1, le=100)
    overall_score: int = Field(ge=1, le=100)
    job_match_score: int = Field(ge=1, le=100)
    behavioral_feedback: str
    technical_feedback: str
    coding_feedback: str
    communication_feedback: str
    job_match_feedback: str
    coding_communication_score: int = Field(ge=1, le=10)
    coding_problem_solving_score: int = Field(ge=1, le=10)
    coding_implementation_score: int = Field(ge=1, le=10)
    coding_complexity_score: int = Field(ge=1, le=10)
    coding_debugging_score: int = Field(ge=1, le=10)
    coding_edge_cases_score: int = Field(ge=1, le=10)
    summary: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    hire_recommendation: str
    recommendation: str
    question_feedback: list[FinalQuestionFeedbackOutput]


def _normalize_final_evaluation_scales(output: FinalEvaluationOutput) -> FinalEvaluationOutput:
    hundred_scale_fields = {
        "behavioral_score": output.behavioral_score,
        "technical_score": output.technical_score,
        "coding_score": output.coding_score,
        "communication_score": output.communication_score,
        "overall_score": output.overall_score,
    }
    if output.job_match_score is not None:
        hundred_scale_fields["job_match_score"] = output.job_match_score

    has_hundred_scale_value = any(value > 10 for value in hundred_scale_fields.values())
    has_ten_scale_value = any(1 <= value <= 10 for value in hundred_scale_fields.values())
    if not has_hundred_scale_value or not has_ten_scale_value:
        return output

    normalized = {
        name: value * 10 if 1 <= value <= 10 else value
        for name, value in hundred_scale_fields.items()
    }
    return output.model_copy(update=normalized)


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


def _question_answer_review_block(session: dict[str, Any]) -> str:
    questions = session.get("questions") or []
    answers = session.get("answers") or []
    answers_by_question_id = {
        str(answer.get("question_id")): str(answer.get("answer_text") or "").strip()
        for answer in answers
        if answer.get("question_id")
    }

    if not questions:
        return "No pre-coding questions were recorded."

    blocks: list[str] = []
    for question in questions:
        question_id = str(question.get("id") or "")
        category = str(question.get("category") or "unknown")
        prompt = str(question.get("prompt") or "").strip()
        answer_text = answers_by_question_id.get(question_id) or "[No answer recorded]"
        blocks.append(
            f"Question ID: {question_id}\n"
            f"Category: {category}\n"
            f"Prompt: {prompt}\n"
            f"Answer: {answer_text}"
        )

    return "\n\n".join(blocks)


def _normalize_code_for_comparison(code: str) -> str:
    lines: list[str] = []
    for raw_line in code.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("//") or line.startswith("#"):
            continue
        lines.append(" ".join(line.split()))
    return "\n".join(lines).strip()


def _coding_evidence_summary(session: dict[str, Any]) -> dict[str, Any]:
    coding_round = session.get("coding_round") or {}
    problem = coding_round.get("problem") or {}
    language = str(coding_round.get("language") or session.get("preferred_language") or "typescript")
    starter_map = problem.get("starter_code") or {}
    starter_code = str(starter_map.get(language) or "")
    current_code = str(coding_round.get("current_code") or "")

    starter_normalized = _normalize_code_for_comparison(starter_code)
    current_normalized = _normalize_code_for_comparison(current_code)
    code_changed = bool(current_normalized) and current_normalized != starter_normalized

    conversation = coding_round.get("conversation") or []
    candidate_messages = [
        turn for turn in conversation
        if str(turn.get("role") or "") == "candidate" and str(turn.get("content") or "").strip()
    ]
    candidate_chars = sum(len(str(turn.get("content") or "").strip()) for turn in candidate_messages)

    transcript = str(coding_round.get("transcript") or "").strip()
    event_log = coding_round.get("event_log") or []
    code_change_events = sum(
        1
        for event in event_log
        if str(event.get("type") or "") == "code_changed"
        and str(event.get("code_excerpt") or "").strip()
    )

    low_signal_explanation = candidate_chars < 100 and len(transcript) < 100
    no_real_progress = not code_changed and code_change_events == 0
    weak_coding_round = no_real_progress and low_signal_explanation

    return {
        "language": language,
        "starter_code_unchanged": not code_changed,
        "code_changed": code_changed,
        "candidate_message_count": len(candidate_messages),
        "candidate_message_chars": candidate_chars,
        "transcript_chars": len(transcript),
        "code_change_events": code_change_events,
        "weak_coding_round": weak_coding_round,
    }


def _coding_mode_for_request(context: OrchestrationContext) -> str:
    if _current_stage(context.session) != "coding":
        return "select_problem"

    coding_round = context.session.get("coding_round") or {}
    if not coding_round.get("problem"):
        return "select_problem"

    if context.action == "resume_stage" and _coding_stage_mode(context.session) == "reading":
        return "followup"

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


def _coding_stage_mode(session: dict[str, Any]) -> str:
    coding_round = session.get("coding_round") or {}
    return str(coding_round.get("current_mode") or "reading")


def _coding_followup_count(session: dict[str, Any]) -> int:
    coding_round = session.get("coding_round") or {}
    conversation = coding_round.get("conversation") or []
    return sum(
        1
        for turn in conversation
        if str(turn.get("role") or "") == "interviewer"
        and str(turn.get("source_event_type") or "") == "followup"
    )


def _coding_last_interviewer_source_event_type(session: dict[str, Any]) -> str:
    coding_round = session.get("coding_round") or {}
    conversation = coding_round.get("conversation") or []
    for turn in reversed(conversation):
        if str(turn.get("role") or "") == "interviewer":
            return str(turn.get("source_event_type") or "").strip()
    return ""


def _coding_last_interviewer_content(session: dict[str, Any]) -> str:
    coding_round = session.get("coding_round") or {}
    conversation = coding_round.get("conversation") or []
    for turn in reversed(conversation):
        if str(turn.get("role") or "") == "interviewer":
            return _strip(str(turn.get("content") or ""))
    return ""


def _coding_round_flag(session: dict[str, Any], name: str) -> bool:
    coding_round = session.get("coding_round") or {}
    return bool(coding_round.get(name))


def _coding_implementation_prompt_count(session: dict[str, Any]) -> int:
    coding_round = session.get("coding_round") or {}
    conversation = coding_round.get("conversation") or []
    count = 0
    after_transition = False
    for turn in conversation:
        if str(turn.get("role") or "") != "interviewer":
            continue
        source_event_type = str(turn.get("source_event_type") or "").strip()
        if source_event_type == "implementation_transition":
            after_transition = True
            continue
        if after_transition and source_event_type in {"followup", "intervene"}:
            count += 1
    return count


def _coding_recent_event_types(context: OrchestrationContext) -> list[str]:
    return [
        str(event.get("type") or "").strip()
        for event in (context.coding_payload.get("recent_client_events") or [])
        if str(event.get("type") or "").strip()
    ]


def _coding_transcript_text(context: OrchestrationContext) -> str:
    return _strip(context.user_input or str(context.coding_payload.get("transcript_recent") or ""))


def _coding_contains_complexity_language(text: str) -> bool:
    lowered = _strip(text).lower()
    return any(
        phrase in lowered
        for phrase in (
            "time complexity",
            "space complexity",
            "big o",
            "o(",
            "linear time",
            "constant space",
            "quadratic",
            "log n",
        )
    )


def _coding_complexity_discussed(
    session: dict[str, Any],
    context: OrchestrationContext | None = None,
) -> bool:
    coding_round = session.get("coding_round") or {}
    conversation = coding_round.get("conversation") or []
    evidence_parts = [str(coding_round.get("transcript") or "")]
    evidence_parts.extend(
        str(turn.get("content") or "")
        for turn in conversation
        if str(turn.get("content") or "").strip()
    )
    if context is not None:
        evidence_parts.append(_coding_transcript_text(context))
        evidence_parts.extend(
            str(event.get("transcript_excerpt") or "")
            for event in (context.coding_payload.get("recent_client_events") or [])
            if str(event.get("transcript_excerpt") or "").strip()
        )
    return _coding_contains_complexity_language("\n".join(evidence_parts))


def _coding_all_evidence_text(session: dict[str, Any]) -> str:
    coding_round = session.get("coding_round") or {}
    conversation = coding_round.get("conversation") or []
    parts = [
        str(coding_round.get("transcript") or ""),
        str(coding_round.get("current_code") or ""),
    ]
    parts.extend(
        str(turn.get("content") or "")
        for turn in conversation
        if str(turn.get("content") or "").strip()
    )
    return "\n".join(part for part in parts if part).strip()


def _coding_contains_edge_case_language(text: str) -> bool:
    lowered = _strip(text).lower()
    return any(
        phrase in lowered
        for phrase in (
            "edge case",
            "empty",
            "null",
            "none",
            "zero",
            "duplicate",
            "single element",
            "overflow",
            "bounds",
            "negative",
            "corner case",
        )
    )


def _coding_edge_case_handling_present(session: dict[str, Any]) -> bool:
    evidence_text = _coding_all_evidence_text(session)
    if _coding_contains_edge_case_language(evidence_text):
        return True

    code = str((session.get("coding_round") or {}).get("current_code") or "").lower()
    return any(
        snippet in code
        for snippet in (
            "if not ",
            "== 0",
            "<= 0",
            ">= len",
            " is none",
            " is null",
            "return []",
            "return -1",
            "return 0",
            "len(",
        )
    )


def _coding_contains_debugging_language(text: str) -> bool:
    lowered = _strip(text).lower()
    return any(
        phrase in lowered
        for phrase in (
            "debug",
            "bug",
            "fixed",
            "fix",
            "error",
            "wrong",
            "issue",
            "test case",
            "failing",
            "failure",
        )
    )


def _coding_debugging_signal_present(session: dict[str, Any]) -> bool:
    coding_round = session.get("coding_round") or {}
    evidence_text = _coding_all_evidence_text(session)
    if _coding_contains_debugging_language(evidence_text):
        return True

    code_change_events = sum(
        1
        for event in (coding_round.get("event_log") or [])
        if str(event.get("type") or "") == "code_changed"
    )
    return code_change_events >= 2


def _coding_has_clarification_signal(context: OrchestrationContext) -> bool:
    transcript = _coding_transcript_text(context).lower()
    event_types = _coding_recent_event_types(context)
    if "clarification_asked" in event_types:
        return True
    return any(token in transcript for token in ("clarify", "constraint", "problem statement", "explain the problem", "help me understand"))


def _coding_has_intervention_signal(context: OrchestrationContext) -> bool:
    transcript = _coding_transcript_text(context).lower()
    event_types = _coding_recent_event_types(context)
    if "candidate_pause" in event_types:
        return True
    return any(token in transcript for token in ("time complexity", "space complexity", "edge case", "stuck", "blocked"))


def _coding_has_user_question_signal(context: OrchestrationContext) -> bool:
    transcript = _coding_transcript_text(context).lower()
    if not transcript:
        return False
    if "?" in transcript:
        return True
    return any(
        transcript.startswith(prefix)
        for prefix in (
            "is ",
            "are ",
            "can ",
            "could ",
            "should ",
            "would ",
            "do ",
            "does ",
            "did ",
            "what ",
            "why ",
            "how ",
            "where ",
            "when ",
        )
    )


def _coding_has_completion_signal(context: OrchestrationContext) -> bool:
    transcript = _coding_transcript_text(context).lower()
    if not transcript:
        return False
    return any(
        phrase in transcript
        for phrase in (
            "i finished",
            "i'm finished",
            "i am finished",
            "i'm done",
            "i am done",
            "done implementing",
            "finished implementing",
            "already finished",
            "solution is complete",
            "implemented the solution",
            "that's my solution",
            "that is my solution",
        )
    )


def _coding_has_code_update_signal(context: OrchestrationContext) -> bool:
    transcript = _coding_transcript_text(context).lower()
    if not transcript:
        return False
    return any(
        phrase in transcript
        for phrase in (
            "i fixed it",
            "i have fixed it",
            "i fixed that",
            "i updated it",
            "i updated the code",
            "i corrected it",
            "i repaired it",
            "i changed it",
            "i have updated the code",
            "i have corrected it",
            "my mistake",
        )
    )


def _coding_has_substantive_answer(context: OrchestrationContext) -> bool:
    transcript = _coding_transcript_text(context)
    return len(transcript) >= 40


def _coding_should_request_specialist(context: OrchestrationContext) -> bool:
    mode = _coding_stage_mode(context.session)
    event_types = _coding_recent_event_types(context)
    transcript = _coding_transcript_text(context)
    user_question = _coding_has_user_question_signal(context)
    completion_signal = _coding_has_completion_signal(context)
    wrap_up_asked = _coding_round_flag(context.session, "wrap_up_question_asked")
    wrap_up_completed = _coding_round_flag(context.session, "wrap_up_completed")
    complexity_discussed = _coding_complexity_discussed(context.session, context)

    if wrap_up_completed:
        return _coding_has_clarification_signal(context) or user_question

    if _coding_has_clarification_signal(context) or _coding_has_intervention_signal(context) or user_question:
        return True

    if context.action == "resume_stage":
        return mode == "reading"

    if context.action != "voice_turn":
        return False

    if mode == "reading":
        return bool(transcript)

    if mode == "discussion":
        if "code_changed" in event_types and not transcript:
            return False
        if not transcript:
            return False
        return _coding_followup_count(context.session) < 2

    if mode == "implementation":
        if (
            not complexity_discussed
            and (
                completion_signal
                or (wrap_up_asked and bool(transcript))
                or (
                    _coding_has_substantive_answer(context)
                    and _coding_last_interviewer_source_event_type(context.session) in {"followup", "intervene"}
                )
            )
        ):
            return True
        if not transcript or "code_changed" in event_types:
            return False
        if completion_signal and not wrap_up_asked:
            return True
        if wrap_up_asked and wrap_up_completed:
            return False
        last_interviewer_event = _coding_last_interviewer_source_event_type(context.session)
        if wrap_up_asked and last_interviewer_event == "followup":
            return False
        if last_interviewer_event in {"followup", "intervene"}:
            return _coding_implementation_prompt_count(context.session) < 2
        return False

    return False


def _coding_implementation_transition_reply() -> str:
    return (
        "Good. That is enough direction to start. Go ahead and implement it now, "
        "and I will only step in if something important comes up."
    )


def _coding_opening_reply(problem_title: str | None = None) -> str:
    if problem_title:
        return f"We'll use {problem_title}. Take about ten seconds to read the prompt, then walk me through your initial approach."
    return "Take about ten seconds to read the prompt, then walk me through your initial approach."


def _coding_initial_approach_question(problem_title: str | None = None) -> str:
    if problem_title:
        return f"What's your initial approach for {problem_title}? Focus on the main idea and the data structures you'd use."
    return "What's your initial approach? Focus on the main idea and the data structures you'd use."


def _coding_wrap_up_completion_reply() -> str:
    return "Thanks. I don't have any more coding questions. You can finish the interview whenever you're ready."


def _coding_positive_completion_reply() -> str:
    return (
        "Thanks, that answers my question and the implementation direction sounds reasonable. "
        "I don't have any more coding questions, so you can finish the interview whenever you're ready."
    )


def _should_skip_followup_for_implementation_transition(
    session: dict[str, Any],
    specialist_output: CodingOutput,
) -> bool:
    return _should_transition_to_implementation_after_followup(session, specialist_output)


def _should_transition_to_implementation_after_followup(
    session: dict[str, Any],
    specialist_output: CodingOutput,
) -> bool:
    projected_followup_count = _coding_followup_count(session)
    if specialist_output.coding_mode == "followup":
        projected_followup_count += 1
    return (
        specialist_output.coding_mode == "followup"
        and _coding_stage_mode(session) == "discussion"
        and projected_followup_count >= 2
        and not _coding_round_flag(session, "implementation_transition_sent")
    )


def _normalize_coding_output_mode(session: dict[str, Any], specialist_output: CodingOutput) -> CodingOutput:
    coding_round = session.get("coding_round") or {}
    problem_selected = bool(coding_round.get("problem"))
    if problem_selected and specialist_output.coding_mode == "select_problem":
        return specialist_output.model_copy(update={"coding_mode": "followup"})
    return specialist_output


def _update_coding_round_mode(session: dict[str, Any], next_mode: str) -> dict[str, Any]:
    coding_round = session.get("coding_round") or {}
    if not coding_round or str(coding_round.get("current_mode") or "") == next_mode:
        return session
    updated_round = {**coding_round, "current_mode": next_mode}
    return {**session, "coding_round": updated_round}


def _update_coding_round_flags(session: dict[str, Any], **flags: bool) -> dict[str, Any]:
    coding_round = session.get("coding_round") or {}
    if not coding_round:
        return session
    updated_round = {**coding_round, **flags}
    return {**session, "coding_round": updated_round}


async def _store_update_coding_mode(session_id: str, session: dict[str, Any], next_mode: str) -> dict[str, Any]:
    updated_session = _update_coding_round_mode(session, next_mode)
    return await _store_save_coding_problem(session_id, updated_session["coding_round"])


async def _store_update_coding_flags(session_id: str, session: dict[str, Any], **flags: bool) -> dict[str, Any]:
    updated_session = _update_coding_round_flags(session, **flags)
    return await _store_save_coding_problem(session_id, updated_session["coding_round"])


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
- For hint, use at most 2 short sentences and do not give the full answer.
- For model_answer, use at most 4 short sentences and keep it practical.
- Stay tightly scoped to the current active prompt.
- Return plain text only. Do not use markdown, bullets, numbering, headings, or code fences.
""".strip()


async def _fetch_problem_candidates(session: dict[str, Any]) -> list[dict[str, Any]]:
    target_company = str(session.get("target_company") or session.get("company_name") or "").strip()
    difficulty = str(session.get("coding_difficulty") or "").strip()

    async with httpx.AsyncClient(timeout=30.0) as client:
        if target_company and difficulty:
            response = await client.get(
                f"{BACKEND_BASE_URL}/api/internal/coding-problems",
                params={"company": target_company, "difficulty": difficulty},
            )
            response.raise_for_status()
            exact_rows = response.json()
            if isinstance(exact_rows, list) and exact_rows:
                return [
                    {
                        "content": str(problem.get("prompt") or ""),
                        "metadata": {
                            "problem_id": str(problem.get("id") or ""),
                            "title": str(problem.get("title") or ""),
                            "company": str(problem.get("company") or ""),
                            "difficulty": str(problem.get("difficulty") or ""),
                            "expected_topics": ", ".join(problem.get("expected_topics") or []),
                            "style_tags": ", ".join(problem.get("style_tags") or []),
                        },
                        "distance": 0.0,
                    }
                    for problem in exact_rows
                    if isinstance(problem, dict)
                ]

    query = "\n".join(
        part
        for part in [
            target_company,
            str(session.get("role_title") or ""),
            difficulty,
            str(session.get("company_context") or "")[:1800],
            str(session.get("job_description_text") or "")[:1800],
        ]
        if part
    ).strip()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BACKEND_BASE_URL}/api/internal/problem-catalog/search",
            json={"query": query, "top_k": 8},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError("Problem catalog search returned invalid payload")
        if difficulty:
            difficulty_matches = [
                row
                for row in data
                if str((row.get("metadata") or {}).get("difficulty") or "").strip().lower() == difficulty.lower()
            ]
            if difficulty_matches:
                return difficulty_matches
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
- If a current problem is already selected, do not talk as if you are selecting a new problem again.
- If the current coding stage mode is reading and there is no candidate transcript yet, ask one short question about the candidate's initial approach.
- In clarify mode, answer only the prompt/constraints/examples question without giving the full solution.
- In followup mode, respond briefly and naturally as the interviewer. Do not keep drilling forever.
- Ask at most one or two follow-up questions after the candidate explains an initial approach, then let them code.
- In implementation mode, do not ask another generic follow-up unless there is a clear clarification or intervention signal.
- Treat the current code excerpt as the source of truth for the implementation. If it is already present, do not ask the candidate to paste or share the code again.
- If the candidate says the implementation is ready or asks you to verify it, inspect the current code directly and respond with a concrete code review observation or a brief confirmation.
- If the candidate says they fixed or updated something after your code review question, re-check the current code before deciding to finish the coding round.
- Before you end the coding round or tell the candidate they can finish the interview, make sure time and space complexity were discussed explicitly.
- If the implementation looks done but complexity has not been discussed yet, ask one short complexity question instead of wrapping up.
- In intervene mode, ask a short pointed question about the candidate's current gap.
- Never invent a new problem outside the catalog.
""".strip()


def _build_final_evaluator_instructions(context: OrchestrationContext) -> str:
    session = context.session
    coding_round = session.get("coding_round") or {}
    coding_evidence = _coding_evidence_summary(session)
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

Coding evidence summary:
- starter_code_unchanged: {coding_evidence["starter_code_unchanged"]}
- code_changed: {coding_evidence["code_changed"]}
- candidate_message_count: {coding_evidence["candidate_message_count"]}
- candidate_message_chars: {coding_evidence["candidate_message_chars"]}
- transcript_chars: {coding_evidence["transcript_chars"]}
- code_change_events: {coding_evidence["code_change_events"]}
- weak_coding_round: {coding_evidence["weak_coding_round"]}

Question and answer review set:
{_question_answer_review_block(session)}

Rules:
- Produce stage-specific feedback for behavioral, technical, coding, and communication.
- Produce a separate job_match_score that reflects how well the candidate's background fits the role overall.
- job_match_score must use both the resume and the interview evidence. Do not treat it as identical to overall interview performance.
- Use the resume as baseline evidence for prior fit, then adjust confidence up or down based on how well the candidate supported that fit in their answers.
- Return matched_requirements and missing_requirements as short concrete bullets phrased as plain strings.
- Provide question_feedback for every recorded pre-coding question using the exact question_id values above.
- Score each section fairly and pragmatically from the actual evidence in the transcript and code. Do not mechanically normalize scores toward the middle.
- The following fields must be integers on a 1-100 scale: behavioral_score, technical_score, coding_score, communication_score, overall_score, and job_match_score.
- The following coding dimension fields must be integers on a 1-10 scale: coding_communication_score, coding_problem_solving_score, coding_implementation_score, coding_complexity_score, coding_debugging_score, and coding_edge_cases_score.
- Do not mix the 1-100 overall fields with the 1-10 coding dimension fields.
- Return explicit coding dimension scores from 1 to 10 for:
  - coding_communication_score
  - coding_problem_solving_score
  - coding_implementation_score
  - coding_complexity_score
  - coding_debugging_score
  - coding_edge_cases_score
- Score each coding dimension independently. Do not flatten all coding dimensions to the same score unless the evidence genuinely supports that.
- Use this coding rubric:
  - `9-10`: exceptional, clearly above normal interview expectations
  - `8`: strong, clearly good performance with only minor gaps
  - `7`: solid, correct or mostly correct with some meaningful room to improve
  - `6`: acceptable but uneven
  - `4-5`: weak
  - `1-3`: clearly poor
- Communication should reflect how clearly the candidate explained the plan, implementation, trade-offs, and decisions while solving.
- Problem solving should reflect decomposition, approach quality, algorithm choice, and adaptability.
- Implementation should reflect code correctness, completeness, quality, and alignment with the intended solution.
- Complexity should reflect the quality of time/space reasoning. Give credit for clear trade-off reasoning even without perfect formal Big-O phrasing.
- Edge cases should reflect whether the candidate identified, covered, or handled important corner cases in discussion or in code.
- Debugging should reflect debugging skill only when debugging or failure analysis was actually relevant. If no debugging was needed because the solution was correct and stable, do not lower the score just for lack of debugging activity.
- If the candidate produced a correct, well-explained solution, it is normal for several coding sub-scores to be 8 or higher.
- Reserve 9/10 and 10/10 for unusually strong performance, not just correct completion.
- Set coding_score from 1 to 100 based primarily on the coding sub-scores and the overall quality of the round. It should usually be close to the sub-score profile rather than contradicting it sharply.
- Use this overall coding calibration:
  - `90-100`: exceptional
  - `80-89`: strong
  - `70-79`: solid
  - `60-69`: mixed / borderline
  - `40-59`: weak
  - `below 40`: clearly poor
- If there was no real implementation progress or the starter code stayed essentially unchanged, score the coding round low. Otherwise, do not artificially hold scores down.
- Keep job_match_score and overall_score separate when needed. A candidate may have a decent background fit but perform weakly in the interview, or the reverse.
- For question_feedback scores, use a 1-10 scale and give one short, concrete sentence per question.
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
    output = _normalize_final_evaluation_scales(output)
    coding_round = session.get("coding_round") or {}
    coding_evaluation = None
    if coding_round.get("problem"):
        coding_evaluation = {
            "communication": output.coding_communication_score,
            "problem_solving": output.coding_problem_solving_score,
            "coding": output.coding_implementation_score,
            "complexity_analysis": output.coding_complexity_score,
            "debugging": output.coding_debugging_score,
            "edge_cases": output.coding_edge_cases_score,
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
        "job_match_score": output.job_match_score,
        "job_match_feedback": output.job_match_feedback,
        "matched_requirements": output.matched_requirements,
        "missing_requirements": output.missing_requirements,
        "recommendation": output.recommendation,
        "question_feedback": [item.model_dump(mode="json") for item in output.question_feedback],
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
        target_company = str(session.get("target_company") or session.get("company_name") or "").strip().lower()
        matched_company = str(selected_problem.get("company") or "").strip()
        matched_company_lower = matched_company.lower()
        selected_difficulty = str(selected_problem.get("difficulty") or "").strip().lower()
        requested_difficulty = str(session.get("coding_difficulty") or "medium").strip().lower()
        if target_company and matched_company_lower == target_company and selected_difficulty == requested_difficulty:
            selection_strategy = "exact_company"
        elif selected_difficulty == requested_difficulty:
            selection_strategy = "difficulty_style_match"
        else:
            selection_strategy = "rag_match"
        coding_round = {
            "enabled": True,
            "target_company": session.get("target_company"),
            "matched_company": matched_company,
            "selection_strategy": selection_strategy,
            "interviewer_mode": session.get("interviewer_mode") or "neutral",
            "difficulty": session.get("coding_difficulty") or "medium",
            "problem": selected_problem,
            "selection_rationale": specialist_output.selection_rationale,
            "language": session.get("preferred_language") or "typescript",
            "editor_mode": "plain" if (session.get("coding_difficulty") or "medium") == "hard" else "monaco",
            "current_code": (selected_problem.get("starter_code") or {}).get(session.get("preferred_language") or "typescript", ""),
            "transcript": "",
            "interviewer_prompt": f"Conduct a concise {session.get('interviewer_mode') or 'neutral'} coding interview.",
            "current_mode": "reading",
            "event_log": [],
            "conversation": [],
            "interventions": [],
            "implementation_transition_sent": False,
            "wrap_up_question_asked": False,
            "wrap_up_completed": False,
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
            "content": _coding_opening_reply(selected_problem.get("title")),
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
        support_content = specialist_output.content.strip()
        current_question = _current_question(session)
        support_entry = {
            "mode": specialist_output.support_mode,
            "stage": _current_stage(session),
            "question_id": current_question.get("id") if current_question else None,
            "content": support_content,
        }
        session = await _store_save_support(session_id, support_entry)
        session = await _store_append_turn(
            session_id,
            {
                "stage": _current_stage(session),
                "role": "interviewer",
                "agent_name": latest_handoff["to_agent"],
                "kind": specialist_output.support_mode,
                "content": support_content,
                "metadata": {},
            },
        )
        return {
            "stage": session.get("current_stage"),
            "active_agent": session.get("active_agent"),
            "handoff": latest_handoff,
            "interviewer_output": support_content,
            "next_prompt": session.get("current_prompt"),
            "ui_patch": {},
            "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
            "is_stage_complete": False,
            "is_interview_complete": False,
            "session": session,
            "final_report": None,
            "support_content": support_content,
        }

    if action in {"voice_turn", "resume_stage"} and _current_stage(session) == "coding":
        if (
            action == "resume_stage"
            and _coding_stage_mode(session) == "reading"
            and not any(
                str(turn.get("role") or "") == "candidate"
                for turn in ((session.get("coding_round") or {}).get("conversation") or [])
            )
        ):
            problem_title = ((session.get("coding_round") or {}).get("problem") or {}).get("title")
            initial_question = _coding_initial_approach_question(problem_title)
            turn = {
                "stage": "coding",
                "role": "interviewer",
                "agent_name": "interview_orchestrator_agent",
                "kind": "coding_reply",
                "content": initial_question,
                "metadata": {"coding_mode": "followup"},
            }
            session = await _store_append_turn(session_id, turn)
            session = await _store_append_coding_message(
                session_id,
                {
                    "role": "interviewer",
                    "content": initial_question,
                    "kind": "reply",
                    "source_event_type": "followup",
                    "severity": None,
                },
            )
            await _store_append_decision_trace(
                session_id,
                {
                    "active_agent": "interview_orchestrator_agent",
                    "decision_type": "initial_coding_prompt",
                    "summary": "Asked the candidate for their high-level approach before any detailed follow-up.",
                    "stage": "coding",
                },
            )
            session = await _store_get_session(session_id)
            return {
                "stage": session.get("current_stage"),
                "active_agent": session.get("active_agent"),
                "handoff": session.get("handoff_history", [])[-1] if session.get("handoff_history") else None,
                "interviewer_output": initial_question,
                "next_prompt": None,
                "ui_patch": {"show_coding_round": True},
                "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
                "is_stage_complete": False,
                "is_interview_complete": False,
                "session": session,
                "final_report": None,
            }

        transitioned_to_implementation = False
        wrap_up_completion_ready = False
        implementation_conclusion_ready = False
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
                if _coding_stage_mode(session) == "reading":
                    session = await _store_update_coding_mode(session_id, session, "discussion")
                elif _coding_stage_mode(session) == "discussion" and _coding_followup_count(session) >= 2:
                    session = await _store_update_coding_mode(session_id, session, "implementation")
                    transitioned_to_implementation = not _coding_round_flag(session, "implementation_transition_sent")

            if "code_changed" in [str(event.get("type") or "") for event in recent_events]:
                if _coding_stage_mode(session) in {"reading", "discussion"}:
                    session = await _store_update_coding_mode(session_id, session, "implementation")
                    transitioned_to_implementation = not _coding_round_flag(session, "implementation_transition_sent")

            context_for_completion = OrchestrationContext(
                action=action,
                session=session,
                user_input=user_input,
                coding_payload=coding_payload,
                ui_context=ui_context or {},
            )
            complexity_discussed = _coding_complexity_discussed(session, context_for_completion)
            if (
                _coding_stage_mode(session) == "implementation"
                and not _coding_round_flag(session, "wrap_up_question_asked")
                and not _coding_round_flag(session, "wrap_up_completed")
                and complexity_discussed
                and not _coding_has_user_question_signal(context_for_completion)
                and not _coding_has_clarification_signal(context_for_completion)
                and not _coding_has_intervention_signal(context_for_completion)
                and not _coding_has_code_update_signal(context_for_completion)
                and _coding_last_interviewer_source_event_type(session) in {"followup", "intervene"}
                and _coding_has_substantive_answer(context_for_completion)
                and _coding_implementation_prompt_count(session) >= 1
            ):
                implementation_conclusion_ready = True
            if (
                _coding_stage_mode(session) == "implementation"
                and _coding_round_flag(session, "wrap_up_question_asked")
                and not _coding_round_flag(session, "wrap_up_completed")
                and complexity_discussed
                and not _coding_has_user_question_signal(context_for_completion)
                and _coding_last_interviewer_source_event_type(session) == "followup"
                and _coding_transcript_text(context_for_completion)
            ):
                wrap_up_completion_ready = True

        if transitioned_to_implementation and not _coding_round_flag(session, "implementation_transition_sent"):
            transition_reply = _coding_implementation_transition_reply()
            session = await _store_update_coding_flags(
                session_id,
                session,
                implementation_transition_sent=True,
            )
            session = await _store_append_turn(
                session_id,
                {
                    "stage": "coding",
                    "role": "interviewer",
                    "agent_name": "interview_orchestrator_agent",
                    "kind": "coding_reply",
                    "content": transition_reply,
                    "metadata": {"coding_mode": "implementation_transition"},
                },
            )
            session = await _store_append_coding_message(
                session_id,
                {
                    "role": "interviewer",
                    "content": transition_reply,
                    "kind": "reply",
                    "source_event_type": "implementation_transition",
                    "severity": None,
                },
            )
            await _store_append_decision_trace(
                session_id,
                {
                    "active_agent": "interview_orchestrator_agent",
                    "decision_type": "implementation_transition",
                    "summary": "Moved the candidate from discussion into implementation.",
                    "stage": "coding",
                },
            )
            session = await _store_get_session(session_id)
            return {
                "stage": session.get("current_stage"),
                "active_agent": session.get("active_agent"),
                "handoff": session.get("handoff_history", [])[-1] if session.get("handoff_history") else None,
                "interviewer_output": transition_reply,
                "next_prompt": None,
                "ui_patch": {"show_coding_round": True},
                "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
                "is_stage_complete": False,
                "is_interview_complete": False,
                "session": session,
                "final_report": None,
            }

        if implementation_conclusion_ready:
            completion_reply = _coding_positive_completion_reply()
            session = await _store_update_coding_flags(
                session_id,
                session,
                wrap_up_completed=True,
            )
            session = await _store_append_turn(
                session_id,
                {
                    "stage": "coding",
                    "role": "interviewer",
                    "agent_name": "interview_orchestrator_agent",
                    "kind": "coding_reply",
                    "content": completion_reply,
                    "metadata": {"coding_mode": "implementation_complete"},
                },
            )
            session = await _store_append_coding_message(
                session_id,
                {
                    "role": "interviewer",
                    "content": completion_reply,
                    "kind": "reply",
                    "source_event_type": "implementation_complete",
                    "severity": None,
                },
            )
            await _store_append_decision_trace(
                session_id,
                {
                    "active_agent": "interview_orchestrator_agent",
                    "decision_type": "implementation_complete",
                    "summary": "Accepted the candidate's answer and ended the coding discussion.",
                    "stage": "coding",
                },
            )
            session = await _store_get_session(session_id)
            return {
                "stage": session.get("current_stage"),
                "active_agent": session.get("active_agent"),
                "handoff": session.get("handoff_history", [])[-1] if session.get("handoff_history") else None,
                "interviewer_output": completion_reply,
                "next_prompt": None,
                "ui_patch": {"show_coding_round": True},
                "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
                "is_stage_complete": False,
                "is_interview_complete": False,
                "session": session,
                "final_report": None,
            }

        if wrap_up_completion_ready:
            completion_reply = _coding_wrap_up_completion_reply()
            session = await _store_update_coding_flags(
                session_id,
                session,
                wrap_up_completed=True,
            )
            session = await _store_append_turn(
                session_id,
                {
                    "stage": "coding",
                    "role": "interviewer",
                    "agent_name": "interview_orchestrator_agent",
                    "kind": "coding_reply",
                    "content": completion_reply,
                    "metadata": {"coding_mode": "wrap_up_complete"},
                },
            )
            session = await _store_append_coding_message(
                session_id,
                {
                    "role": "interviewer",
                    "content": completion_reply,
                    "kind": "reply",
                    "source_event_type": "wrap_up_complete",
                    "severity": None,
                },
            )
            await _store_append_decision_trace(
                session_id,
                {
                    "active_agent": "interview_orchestrator_agent",
                    "decision_type": "wrap_up_complete",
                    "summary": "Finished the final coding wrap-up and invited the candidate to end the interview.",
                    "stage": "coding",
                },
            )
            session = await _store_get_session(session_id)
            return {
                "stage": session.get("current_stage"),
                "active_agent": session.get("active_agent"),
                "handoff": session.get("handoff_history", [])[-1] if session.get("handoff_history") else None,
                "interviewer_output": completion_reply,
                "next_prompt": None,
                "ui_patch": {"show_coding_round": True},
                "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
                "is_stage_complete": False,
                "is_interview_complete": False,
                "session": session,
                "final_report": None,
            }

        if not _coding_should_request_specialist(
            OrchestrationContext(
                action=action,
                session=session,
                user_input=user_input,
                coding_payload=coding_payload,
                ui_context=ui_context or {},
            )
        ):
            session = await _store_get_session(session_id)
            return {
                "stage": session.get("current_stage"),
                "active_agent": session.get("active_agent"),
                "handoff": session.get("handoff_history", [])[-1] if session.get("handoff_history") else None,
                "interviewer_output": None,
                "next_prompt": None,
                "ui_patch": {"show_coding_round": True},
                "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
                "is_stage_complete": False,
                "is_interview_complete": False,
                "session": session,
                "final_report": None,
            }

        context = OrchestrationContext(
            action=action,
            session=session,
            user_input=user_input,
            coding_payload=coding_payload,
            ui_context=ui_context or {},
        )
        completion_signal = _coding_has_completion_signal(context)
        specialist_output = await _run_specialist(context)
        specialist_output = _normalize_coding_output_mode(session, specialist_output)
        latest_handoff = context.handoff_log[-1]
        await _store_set_active_agent(session_id, latest_handoff["to_agent"])
        await _store_record_handoff(session_id, latest_handoff)
        if not isinstance(specialist_output, CodingOutput):
            raise RuntimeError("Expected coding output during coding stage")

        message_kind = "intervention" if specialist_output.coding_mode == "intervene" else "coding_reply"
        reply_text = specialist_output.reply.strip()
        last_interviewer_content = _coding_last_interviewer_content(session)
        skip_followup_for_transition = _should_skip_followup_for_implementation_transition(
            session,
            specialist_output,
        )
        surfaced_reply_text: str | None = None
        if reply_text and reply_text == last_interviewer_content:
            await _store_append_decision_trace(
                session_id,
                {
                    "active_agent": latest_handoff["to_agent"],
                    "decision_type": "duplicate_reply_suppressed",
                    "summary": "Suppressed a repeated coding follow-up.",
                    "stage": "coding",
                },
            )
            session = await _store_get_session(session_id)
            return {
                "stage": session.get("current_stage"),
                "active_agent": session.get("active_agent"),
                "handoff": latest_handoff,
                "interviewer_output": None,
                "next_prompt": None,
                "ui_patch": {"show_coding_round": True},
                "decision_trace_entry": session.get("decision_trace", [])[-1] if session.get("decision_trace") else None,
                "is_stage_complete": False,
                "is_interview_complete": False,
                "session": session,
                "final_report": None,
            }
        if reply_text and not skip_followup_for_transition:
            interviewer_turn = {
                "stage": "coding",
                "role": "interviewer",
                "agent_name": latest_handoff["to_agent"],
                "kind": message_kind,
                "content": reply_text,
                "metadata": {"coding_mode": specialist_output.coding_mode},
            }
            session = await _store_append_turn(session_id, interviewer_turn)
            session = await _store_append_coding_message(
                session_id,
                {
                    "role": "interviewer",
                    "content": reply_text,
                    "kind": "intervention" if specialist_output.coding_mode == "intervene" else "reply",
                    "source_event_type": specialist_output.coding_mode,
                    "severity": "medium" if specialist_output.coding_mode == "intervene" else None,
                },
            )
            surfaced_reply_text = reply_text
        elif skip_followup_for_transition:
            await _store_append_decision_trace(
                session_id,
                {
                    "active_agent": latest_handoff["to_agent"],
                    "decision_type": "followup_suppressed_for_transition",
                    "summary": "Skipped the final follow-up because the round is moving directly into implementation.",
                    "stage": "coding",
                },
            )
        if specialist_output.coding_mode == "followup" and _coding_stage_mode(session) == "reading":
            session = await _store_update_coding_mode(session_id, session, "discussion")
        elif _should_transition_to_implementation_after_followup(session, specialist_output):
            session = await _store_update_coding_mode(session_id, session, "implementation")
            session = await _store_update_coding_flags(
                session_id,
                session,
                implementation_transition_sent=True,
            )
            transition_reply = _coding_implementation_transition_reply()
            session = await _store_append_turn(
                session_id,
                {
                    "stage": "coding",
                    "role": "interviewer",
                    "agent_name": "interview_orchestrator_agent",
                    "kind": "coding_reply",
                    "content": transition_reply,
                    "metadata": {"coding_mode": "implementation_transition"},
                },
            )
            session = await _store_append_coding_message(
                session_id,
                {
                    "role": "interviewer",
                    "content": transition_reply,
                    "kind": "reply",
                    "source_event_type": "implementation_transition",
                    "severity": None,
                },
            )
            surfaced_reply_text = transition_reply
        elif completion_signal and specialist_output.coding_mode == "followup":
            session = await _store_update_coding_flags(
                session_id,
                session,
                wrap_up_question_asked=True,
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
            "interviewer_output": surfaced_reply_text,
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
