import json
import logging
import os
from typing import Any

from agents import Agent, Runner


OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
logger = logging.getLogger("interview-prep-agents.workflow")

_structured_agents: dict[str, Agent] = {}


def _strip_json_fence(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
        if candidate.endswith("```"):
            candidate = candidate[:-3]
    return candidate.strip()


def _get_structured_agent(name: str, instructions: str) -> Agent:
    cached = _structured_agents.get(name)
    if cached is not None:
        return cached

    agent = Agent(
        name=name,
        instructions=instructions,
        model=OPENAI_MODEL,
    )
    _structured_agents[name] = agent
    return agent


async def _run_agent_text(*, name: str, instructions: str, prompt: str) -> str:
    agent = _get_structured_agent(name, instructions)
    try:
        result = await Runner.run(agent, input=prompt)
    except Exception:
        logger.exception("agent run failed name=%s", name)
        raise

    final_output = getattr(result, "final_output", "")
    if isinstance(final_output, str):
        return final_output.strip()
    if final_output is None:
        return ""
    return str(final_output).strip()


async def _run_agent_json(*, name: str, instructions: str, prompt: str) -> dict[str, Any]:
    text = await _run_agent_text(name=name, instructions=instructions, prompt=prompt)
    parsed = json.loads(_strip_json_fence(text))
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Agent {name} did not return a JSON object")
    return parsed


async def build_interview_plan_with_agent(
    *,
    resume_text: str,
    job_description_text: str,
    interview_length: str,
    behavioral_count: int,
    technical_count: int,
) -> dict[str, Any]:
    prompt = f"""
Create a complete interview plan as strict JSON.

Interview length: {interview_length}
Behavioral questions required: {behavioral_count}
Technical questions required: {technical_count}

Resume:
{resume_text}

Job description:
{job_description_text}

Return JSON with this exact shape:
{{
  "role_title": "short role title",
  "questions": [
    {{"id": "behavioral-1", "category": "behavioral", "prompt": "..."}} ,
    {{"id": "technical-1", "category": "technical", "prompt": "..."}}
  ]
}}

Rules:
- Return exactly {behavioral_count + technical_count} questions.
- The first {behavioral_count} must be behavioral.
- The remaining {technical_count} must be technical.
- Each question must be tailored to the candidate and role.
- Do not wrap the JSON in markdown fences.
""".strip()

    return await _run_agent_json(
        name="interview_planner_agent",
        instructions=(
            "You are an interview planner agent. "
            "Design realistic, role-specific interview plans. "
            "Return only valid JSON that exactly matches the requested schema."
        ),
        prompt=prompt,
    )


async def build_interview_report_with_agent(
    *,
    role_title: str,
    interview_length: str,
    resume_text: str,
    job_description_text: str,
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    coding_feedback_input: str | None = None,
    coding_hire_recommendation: str | None = None,
) -> dict[str, Any]:
    coding_block = ""
    if coding_feedback_input:
        coding_block = (
            "\nCoding round context:\n"
            f"- Coding evaluation summary: {coding_feedback_input}\n"
            f"- Coding hire signal: {coding_hire_recommendation or 'not provided'}\n"
        )

    prompt = f"""
Evaluate the completed interview and return strict JSON only.

Role title: {role_title}
Interview length: {interview_length}

Resume:
{resume_text}

Job description:
{job_description_text}

Questions:
{json.dumps(questions, ensure_ascii=True, indent=2)}

Answers:
{json.dumps(answers, ensure_ascii=True, indent=2)}
{coding_block}

Return JSON with this exact shape:
{{
  "score": <integer 1-100>,
  "summary": "2-3 sentence summary",
  "strengths": ["...", "...", "..."],
  "improvements": ["...", "...", "..."],
  "behavioral_feedback": "...",
  "technical_feedback": "...",
  "communication_feedback": "...",
  "recommendation": "...",
  "question_feedback": [
    {{"question_id": "behavioral-1", "score": 8, "feedback": "..."}}
  ],
  "coding_feedback": "...",
  "hire_recommendation": "strong_hire|hire|lean_hire|lean_no_hire|no_hire"
}}

Rules:
- Score must be an integer from 1 to 100.
- Include one question_feedback item per answer.
- Keep strengths and improvements concrete and actionable.
- If coding context is present, include it in the final recommendation and coding_feedback.
- Do not wrap the JSON in markdown fences.
""".strip()

    return await _run_agent_json(
        name="interview_report_agent",
        instructions=(
            "You are an interview report agent. "
            "Synthesize behavioral, technical, communication, and coding evidence into a pragmatic assessment. "
            "Return only strict JSON matching the requested schema."
        ),
        prompt=prompt,
    )


async def build_interview_help_with_agent(
    *,
    help_kind: str,
    role_title: str,
    question: dict[str, Any],
    resume_text: str,
    job_description_text: str,
) -> dict[str, Any]:
    intent_line = (
        "Provide a short hint that points the user in the right direction without giving the full answer."
        if help_kind == "hint"
        else "Provide a strong sample answer the user could study as the correct answer."
    )

    prompt = f"""
You are helping a user answer an interview question.

Role title: {role_title}
Question category: {question.get("category", "")}
Question:
{question.get("prompt", "")}

Resume:
{resume_text}

Job description:
{job_description_text}

Task:
{intent_line}

Return strict JSON with this exact shape:
{{
  "content": "..."
}}

Rules:
- For `hint`, keep it under 80 words and do not reveal the full answer.
- For `model_answer`, keep it practical, polished, and specific.
- Do not wrap the JSON in markdown fences.
""".strip()

    return await _run_agent_json(
        name="interview_help_agent",
        instructions=(
            "You are an interview help agent. "
            "Support the candidate without drifting off-topic. "
            "Return only strict JSON matching the requested schema."
        ),
        prompt=prompt,
    )


async def build_coding_reply_with_agent(
    *,
    interviewer_prompt: str,
    problem_title: str,
    problem_prompt: str,
    problem_constraints: list[str],
    problem_examples: list[dict[str, Any]],
    edge_case_hints: list[str],
    complexity_target: str | None,
    interviewer_mode: str,
    recent_event_types: list[str],
    transcript_recent: str,
    current_code: str,
    conversation: list[dict[str, Any]],
    forced_followup: str | None = None,
) -> dict[str, Any]:
    conversation_block = "\n".join(
        f"{str(turn.get('role', 'unknown')).title()}: {str(turn.get('content', '')).strip()}"
        for turn in conversation[-8:]
        if str(turn.get("content", "")).strip()
    ) or "No prior coding dialogue yet."
    constraints_block = "\n".join(f"- {constraint}" for constraint in problem_constraints[:6]) or "- No explicit constraints provided."
    examples_block = "\n".join(
        f"- Input: {str(example.get('input', '')).strip()} | Output: {str(example.get('output', '')).strip()}"
        + (
            f" | Explanation: {str(example.get('explanation', '')).strip()}"
            if str(example.get("explanation", "")).strip()
            else ""
        )
        for example in problem_examples[:3]
    ) or "- No examples provided."
    edge_cases_block = "\n".join(f"- {hint}" for hint in edge_case_hints[:6]) or "- Use only edge cases implied by the prompt and constraints."

    prompt = f"""
Continue a live coding interview as strict JSON only.

Interviewer mode: {interviewer_mode}
Problem title: {problem_title}
Problem prompt:
{problem_prompt}
Problem constraints:
{constraints_block}

Representative examples:
{examples_block}

Target complexity:
{complexity_target or "Not explicitly specified"}

Valid edge-case directions:
{edge_cases_block}

Recent event types: {", ".join(recent_event_types) or "none"}
Candidate just said:
{transcript_recent}

Current code excerpt:
{current_code[-1600:]}

Recent conversation:
{conversation_block}

Forced follow-up if needed:
{forced_followup or "none"}

Return JSON with this exact shape:
{{
  "reply": "short interviewer reply"
}}

Rules:
- Follow this system guidance closely: {interviewer_prompt or 'Be a concise FAANG-style interviewer.'}
- Reply as the interviewer, not as a coach.
- Keep it short: one or two sentences.
- If the candidate asked for clarification, answer that request directly first using constraints/examples-level clarification.
- Do not reveal the full algorithm or write code for them.
- Do not ask about impossible scenarios that contradict the stated constraints.
- When you ask about edge cases, prefer the provided valid edge-case directions over inventing new invalid ones.
- If a follow-up question helps, ask exactly one pointed question.
- If the candidate is simply thinking aloud, engage with what they said instead of ignoring it.
- If the candidate already answered your last question, acknowledge it and move forward instead of repeating yourself.
- Do not ignore the candidate's most recent utterance.
- Return only valid JSON and no markdown fences.
""".strip()

    return await _run_agent_json(
        name="coding_interviewer_agent",
        instructions=(
            "You are a coding interviewer agent for a realistic FAANG-style interview. "
            "You stay concise, respond to clarifications directly, and never give the full solution. "
            "Return only strict JSON matching the requested schema."
        ),
        prompt=prompt,
    )


async def evaluate_coding_round_with_agent(
    *,
    problem_title: str,
    problem_prompt: str,
    difficulty: str,
    language: str,
    complexity_target: str | None,
    current_code: str,
    transcript: str,
    conversation: list[dict[str, Any]],
    event_log: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = f"""
Evaluate a completed coding interview round and return strict JSON only.

Problem title: {problem_title}
Difficulty: {difficulty}
Language: {language}
Problem prompt:
{problem_prompt}
Target complexity:
{complexity_target or "Not specified"}

Transcript:
{transcript[-5000:]}

Conversation:
{json.dumps(conversation[-16:], ensure_ascii=True, indent=2)}

Event log:
{json.dumps(event_log[-30:], ensure_ascii=True, indent=2)}

Current code:
{current_code[-6000:]}

Return JSON with this exact shape:
{{
  "communication": 1,
  "problem_solving": 1,
  "coding": 1,
  "complexity_analysis": 1,
  "debugging": 1,
  "edge_cases": 1,
  "overall_score": 1,
  "hire_recommendation": "strong_hire|hire|lean_hire|lean_no_hire|no_hire",
  "summary": "...",
  "strengths": ["...", "..."],
  "concerns": ["...", "..."]
}}

Rules:
- Category scores must be integers from 1 to 10.
- overall_score must be an integer from 1 to 100.
- Base the judgment on the transcript, code, and conversation together.
- Keep strengths and concerns concrete.
- Return only valid JSON and no markdown fences.
""".strip()

    return await _run_agent_json(
        name="coding_evaluator_agent",
        instructions=(
            "You are a coding interview evaluator agent. "
            "Score communication, problem solving, coding, complexity analysis, debugging, and edge cases fairly and pragmatically. "
            "Return only strict JSON matching the requested schema."
        ),
        prompt=prompt,
    )
