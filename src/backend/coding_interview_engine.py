from __future__ import annotations

import re

from pydantic import BaseModel

from interview_data_store import (
    CodingInterviewEventModel,
    CodingInterviewRoundModel,
    CodingInterventionModel,
    CodingProblemModel,
)


MODE_GUIDANCE = {
    "warm": "Supportive, calm, and lightly encouraging while still rigorous.",
    "neutral": "Direct, concise, and professional.",
    "bar_raiser": "Sharper, more demanding, and skeptical about gaps in reasoning.",
    "silent": "Very low-frequency intervention mode. Only step in when there is a clear interview signal.",
}

REASON_ORDER = [
    "candidate_stuck",
    "inefficient_solution",
    "missing_edge_cases",
    "complexity_not_discussed",
    "long_pause",
]

QUESTION_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "complexity_not_discussed": (
        "complexity-check",
        "What's the time and space complexity here?",
        "medium",
    ),
    "long_pause": (
        "resume-thinking",
        "Talk me through what you're considering right now.",
        "low",
    ),
    "inefficient_solution": (
        "reduce-work",
        "Is there a way to avoid repeating that work for every element?",
        "high",
    ),
    "missing_edge_cases": (
        "edge-case-check",
        "Which edge cases would you test before you call this done?",
        "medium",
    ),
    "candidate_stuck": (
        "smaller-slice",
        "What smaller version of the problem can you solve first?",
        "high",
    ),
}

LONG_PAUSE_THRESHOLD_SECONDS = 45

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "complexity": (
        "time complexity",
        "space complexity",
        "big o",
        "o(",
        "linear",
        "constant",
        "quadratic",
        "log n",
    ),
    "edge_cases": (
        "edge case",
        "empty",
        "null",
        "zero",
        "duplicate",
        "single element",
        "negative",
        "corner case",
        "bounds",
    ),
    "tradeoffs": (
        "tradeoff",
        "trade-off",
        "space",
        "memory",
        "optimize",
        "faster",
        "slower",
        "simpler",
        "complex",
    ),
    "debugging": (
        "debug",
        "test",
        "trace",
        "bug",
        "fix",
        "check",
        "verify",
    ),
    "clarification": (
        "clarify",
        "constraint",
        "input",
        "output",
        "example",
        "allowed",
        "guaranteed",
        "meaning",
        "enunt",
        "statement",
    ),
}

CLARIFICATION_HINTS: tuple[str, ...] = (
    "clarify",
    "clarification",
    "help me understand",
    "understand the problem",
    "understand the prompt",
    "understand the statement",
    "problem statement",
    "explain the problem",
    "explain the prompt",
    "explain the statement",
    "restate the problem",
    "what does the problem mean",
    "what does that mean",
    "walk me through the prompt",
    "walk me through the problem",
    "constraint",
    "constraints",
    "allowed",
    "guaranteed",
    "input format",
    "output format",
    "example",
    "examples",
    "meaning",
    "enunt",
)

REASONING_UPDATE_HINTS: tuple[str, ...] = (
    "i think",
    "i'm thinking",
    "i am thinking",
    "i'm considering",
    "i am considering",
    "my approach",
    "the approach",
    "the idea",
    "i would",
    "i will",
    "i can",
    "i could",
    "maybe",
    "first",
    "then",
    "start with",
    "use a",
    "use an",
    "hash",
    "map",
    "sort",
    "scan",
    "iterate",
    "pointer",
    "window",
    "stack",
    "queue",
    "binary search",
    "recursion",
    "dynamic programming",
)


class CodingProblemSelectionResultModel(BaseModel):
    problem: CodingProblemModel
    matched_company: str
    selection_strategy: str


class CodingInterventionDecisionModel(BaseModel):
    should_interrupt: bool
    reason: str | None = None
    question: str | None = None
    severity: str = "none"
    prompt_key: str | None = None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.-]{2,}", _normalize(text)))


def _clamp_score(value: float) -> int:
    return max(1, min(10, int(round(value))))


def looks_like_clarification_request(text: str) -> bool:
    lowered = _normalize(text)
    if not lowered:
        return False
    return any(hint in lowered for hint in CLARIFICATION_HINTS)


def looks_like_reasoning_update(text: str) -> bool:
    lowered = _normalize(text)
    if not lowered or looks_like_clarification_request(lowered):
        return False
    if len(lowered.split()) < 4:
        return False
    return any(hint in lowered for hint in REASONING_UPDATE_HINTS)


def build_ai_interviewer_prompt(mode: str, problem: CodingProblemModel) -> str:
    guidance = MODE_GUIDANCE.get(mode, MODE_GUIDANCE["neutral"])
    examples_block = "\n".join(
        f"- Input: {example.input} | Output: {example.output}"
        for example in problem.examples[:2]
    )
    constraints_block = "\n".join(f"- {constraint}" for constraint in problem.constraints[:4]) or "- Use the stated prompt constraints."
    edge_case_block = "\n".join(f"- {hint}" for hint in problem.edge_case_hints[:4]) or "- Ask only about edge cases consistent with the prompt."

    return (
        "You are an AI coding interviewer running a realistic FAANG-style interview.\n"
        f"Interviewer mode: {mode}. Tone guidance: {guidance}\n\n"
        "Rules:\n"
        "- Do not give the full solution.\n"
        "- Keep questions short and natural.\n"
        "- Behave like a strong FAANG interviewer.\n"
        "- Ask about complexity, edge cases, trade-offs, debugging, and correctness.\n"
        "- Do not interrupt too often.\n"
        "- Periodically evaluate whether the candidate's code seems correct or inefficient.\n"
        "- If the candidate asks for clarification, restate constraints or examples without revealing the algorithm.\n"
        "- Never ask about an impossible case that contradicts the stated constraints.\n"
        "- Prefer one pointed follow-up instead of a long explanation.\n\n"
        f"Problem: {problem.title}\n"
        f"Company style: {problem.company}\n"
        f"Difficulty: {problem.difficulty}\n"
        f"Prompt: {problem.prompt}\n"
        f"Target complexity: {problem.complexity_target or 'Ask the candidate to justify complexity explicitly.'}\n"
        "Constraints:\n"
        f"{constraints_block}\n"
        "Representative examples:\n"
        f"{examples_block}\n"
        "Valid edge-case directions:\n"
        f"{edge_case_block}\n"
    )


def choose_coding_problem(
    *,
    problems: list[CodingProblemModel],
    target_company: str | None,
    desired_difficulty: str,
    role_title: str,
    job_description_text: str,
) -> CodingProblemSelectionResultModel:
    company = _normalize(target_company or "")
    role_tokens = _tokenize(f"{role_title} {job_description_text}")

    exact_matches = [
        problem
        for problem in problems
        if _normalize(problem.company) == company and problem.difficulty == desired_difficulty
    ]
    if exact_matches:
        return CodingProblemSelectionResultModel(
            problem=exact_matches[0],
            matched_company=exact_matches[0].company,
            selection_strategy="exact_company",
        )

    difficulty_matches = [problem for problem in problems if problem.difficulty == desired_difficulty]
    pool = difficulty_matches or problems

    scored: list[tuple[int, CodingProblemModel]] = []
    for problem in pool:
        problem_tokens = _tokenize(
            " ".join(
                [
                    problem.company,
                    problem.title,
                    " ".join(problem.style_tags),
                    " ".join(problem.expected_topics),
                ]
            )
        )
        overlap = len(role_tokens & problem_tokens)
        if company and company in _normalize(problem.company):
            overlap += 6
        if desired_difficulty == problem.difficulty:
            overlap += 2
        scored.append((overlap, problem))

    scored.sort(key=lambda item: (item[0], item[1].title), reverse=True)
    selected = scored[0][1]
    return CodingProblemSelectionResultModel(
        problem=selected,
        matched_company=selected.company,
        selection_strategy="style_match" if company else "difficulty_match",
    )


def _contains_complexity_language(text: str) -> bool:
    lowered = _normalize(text)
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


def _contains_edge_case_language(text: str) -> bool:
    lowered = _normalize(text)
    return any(
        phrase in lowered
        for phrase in (
            "edge case",
            "empty",
            "null",
            "zero",
            "duplicate",
            "single element",
            "overflow",
            "bounds",
            "negative",
            "corner case",
        )
    )


def _nested_loop_signal(code: str) -> bool:
    loop_hits = re.findall(r"\b(for|while)\b", code)
    if len(loop_hits) >= 2:
        return True
    return code.count(".sort(") > 1 or "for (" in code and ".slice(" in code


def _meaningful_code_lines(code: str) -> list[str]:
    meaningful_lines: list[str] = []
    for raw_line in code.splitlines():
        line = _normalize(raw_line)
        if not line:
            continue
        if line.startswith("//") or line.startswith("#"):
            continue
        if line in {"{", "}", "};"}:
            continue
        if any(
            placeholder in line
            for placeholder in (
                "return null",
                "return none",
                'return ""',
                "return -1",
                "pass",
                "todo",
                "explain your thinking as you code",
            )
        ):
            continue
        meaningful_lines.append(line)
    return meaningful_lines


def _candidate_sounds_stuck(text: str) -> bool:
    lowered = _normalize(text)
    return any(
        phrase in lowered
        for phrase in (
            "i'm stuck",
            "not sure",
            "i do not know",
            "i don't know",
            "hmm",
            "let me think",
            "confused",
            "blanking",
            "explain the problem",
            "explain the statement",
        )
    )


def _detect_topics(text: str) -> set[str]:
    lowered = _normalize(text)
    topics: set[str] = set()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            topics.add(topic)
    return topics


def _has_meaningful_code_progress(round_state: CodingInterviewRoundModel, code: str) -> bool:
    current_lines = _meaningful_code_lines(code)
    if not current_lines:
        return False

    starter_code = ""
    if round_state.problem:
        starter_code = round_state.problem.starter_code.get(round_state.language, "")
    starter_lines = set(_meaningful_code_lines(starter_code))

    if any(line not in starter_lines for line in current_lines):
        return True

    return _event_count(round_state.event_log, "code_changed") >= 2 and len(current_lines) >= 2


def _is_ready_for_solution_review(
    round_state: CodingInterviewRoundModel,
    code: str,
) -> bool:
    if _has_meaningful_code_progress(round_state, code):
        return True
    if _event_count(round_state.event_log, "solution_explained") >= 1:
        return True
    return False


def _latest_interviewer_question(round_state: CodingInterviewRoundModel) -> str:
    for turn in reversed(round_state.conversation):
        if turn.role == "interviewer" and turn.content.strip():
            return turn.content
    return ""


def _response_addresses_latest_question(round_state: CodingInterviewRoundModel, transcript_recent: str) -> bool:
    latest_question = _latest_interviewer_question(round_state)
    if not latest_question.strip() or not transcript_recent.strip():
        return False

    if looks_like_clarification_request(transcript_recent):
        return False

    question_topics = _detect_topics(latest_question)
    answer_topics = _detect_topics(transcript_recent)
    if question_topics and question_topics & answer_topics:
        return True

    lowered_answer = _normalize(transcript_recent)
    lowered_question = _normalize(latest_question)
    if "what's the time and space complexity" in lowered_question:
        return _contains_complexity_language(lowered_answer)
    if "edge cases" in lowered_question:
        return _contains_edge_case_language(lowered_answer)
    if "trade-off" in lowered_question or "tradeoff" in lowered_question:
        return "tradeoff" in lowered_answer or "trade-off" in lowered_answer or "because" in lowered_answer
    if "blocking you" in lowered_question or "considering right now" in lowered_question:
        return looks_like_reasoning_update(lowered_answer)
    return False


def _event_count(events: list[CodingInterviewEventModel], event_type: str) -> int:
    return sum(1 for event in events if event.type == event_type)


class InterviewInterventionEngine:
    def decide(
        self,
        *,
        round_state: CodingInterviewRoundModel,
        transcript_recent: str,
        recent_events: list[CodingInterviewEventModel],
        elapsed_time_seconds: int,
        code: str,
    ) -> CodingInterventionDecisionModel:
        cooldown_seconds = round_state.cooldown_seconds
        if round_state.interviewer_mode == "silent":
            cooldown_seconds = max(cooldown_seconds, 60)

        if (
            any(event.type == "clarification_asked" for event in recent_events)
            or looks_like_clarification_request(transcript_recent)
        ) and transcript_recent.strip():
            return CodingInterventionDecisionModel(should_interrupt=False)

        if round_state.last_intervention_at and recent_events:
            seconds_since_last_event = int(
                (recent_events[-1].created_at - round_state.last_intervention_at).total_seconds()
            )
            if seconds_since_last_event < cooldown_seconds:
                return CodingInterventionDecisionModel(should_interrupt=False)

        if round_state.last_intervention_at is None and elapsed_time_seconds < 25:
            return CodingInterventionDecisionModel(should_interrupt=False)

        if _response_addresses_latest_question(round_state, transcript_recent):
            return CodingInterventionDecisionModel(should_interrupt=False)

        asked_prompt_keys = {
            intervention.prompt_key or _normalize(intervention.question)
            for intervention in round_state.interventions
        }
        combined_text = "\n".join(
            filter(
                None,
                [
                    transcript_recent,
                    round_state.transcript,
                    *(event.transcript_excerpt or "" for event in recent_events),
                ],
            )
        )
        lowered_code = _normalize(code)
        has_solution_progress = _is_ready_for_solution_review(round_state, code)

        reasons: list[str] = []
        if _candidate_sounds_stuck(combined_text) or _event_count(recent_events, "clarification_asked") >= 2:
            reasons.append("candidate_stuck")

        if has_solution_progress and _nested_loop_signal(code) and round_state.problem:
            expected = " ".join(round_state.problem.expected_topics).lower()
            if "sliding window" in expected or "binary search" in expected or "hash map" in expected:
                reasons.append("inefficient_solution")

        if has_solution_progress and elapsed_time_seconds >= 120 and not _contains_edge_case_language(combined_text):
            reasons.append("missing_edge_cases")

        if has_solution_progress and elapsed_time_seconds >= 150 and not _contains_complexity_language(combined_text):
            reasons.append("complexity_not_discussed")

        pause_events = [
            event
            for event in recent_events
            if event.type == "candidate_pause"
            and float(event.metadata.get("duration_seconds", 0) or 0) >= LONG_PAUSE_THRESHOLD_SECONDS
        ]
        if pause_events:
            reasons.append("long_pause")

        if round_state.interviewer_mode == "silent":
            reasons = [reason for reason in reasons if reason in {"candidate_stuck", "inefficient_solution"}]

        recent_topics = _detect_topics(transcript_recent)
        if "complexity" in recent_topics:
            reasons = [reason for reason in reasons if reason != "complexity_not_discussed"]
        if "edge_cases" in recent_topics:
            reasons = [reason for reason in reasons if reason != "missing_edge_cases"]

        for reason in REASON_ORDER:
            if reason not in reasons:
                continue

            prompt_key, question, severity = QUESTION_TEMPLATES[reason]
            if prompt_key in asked_prompt_keys or question in asked_prompt_keys:
                continue

            return CodingInterventionDecisionModel(
                should_interrupt=True,
                reason=reason,
                question=question,
                severity=severity,
                prompt_key=prompt_key,
            )

        return CodingInterventionDecisionModel(should_interrupt=False)


def apply_intervention(
    round_state: CodingInterviewRoundModel,
    decision: CodingInterventionDecisionModel,
) -> CodingInterviewRoundModel:
    if not decision.should_interrupt or not decision.question or not decision.reason:
        return round_state

    return round_state.model_copy(
        update={
            "interventions": [
                *round_state.interventions,
                CodingInterventionModel(
                    question=decision.question,
                    reason=decision.reason,
                    severity=decision.severity,
                    prompt_key=decision.prompt_key,
                ),
            ],
            "last_intervention_at": round_state.started_at if not round_state.event_log else round_state.event_log[-1].created_at,
            "latest_reason": decision.reason,
        }
    )
