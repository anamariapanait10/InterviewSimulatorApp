from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CodingProblemExampleModel(BaseModel):
    input: str
    output: str
    explanation: str | None = None


class CodingProblemModel(BaseModel):
    id: str
    title: str
    company: str
    difficulty: str
    prompt: str
    constraints: list[str] = Field(default_factory=list)
    examples: list[CodingProblemExampleModel] = Field(default_factory=list)
    starter_code: dict[str, str] = Field(default_factory=dict)
    expected_topics: list[str] = Field(default_factory=list)
    style_tags: list[str] = Field(default_factory=list)
    complexity_target: str | None = None
    edge_case_hints: list[str] = Field(default_factory=list)


class CodingInterviewEventModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    created_at: datetime = Field(default_factory=utcnow)
    transcript_excerpt: str | None = None
    code_excerpt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodingInterventionModel(BaseModel):
    question: str
    reason: str
    severity: str
    created_at: datetime = Field(default_factory=utcnow)
    prompt_key: str | None = None


class CodingConversationTurnModel(BaseModel):
    role: str
    content: str
    created_at: datetime = Field(default_factory=utcnow)
    kind: str = "message"
    source_event_type: str | None = None
    severity: str | None = None


class CodingInterviewEvaluationModel(BaseModel):
    communication: int
    problem_solving: int
    coding: int
    complexity_analysis: int
    debugging: int
    edge_cases: int
    overall_score: int
    hire_recommendation: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


class CodingInterviewRoundModel(BaseModel):
    enabled: bool = True
    target_company: str | None = None
    matched_company: str | None = None
    selection_strategy: str = "exact_company"
    interviewer_mode: str = "neutral"
    difficulty: str = "medium"
    problem: CodingProblemModel | None = None
    selection_rationale: str | None = None
    language: str = "typescript"
    editor_mode: str = "monaco"
    current_code: str = ""
    transcript: str = ""
    interviewer_prompt: str | None = None
    current_mode: str | None = None
    event_log: list[CodingInterviewEventModel] = Field(default_factory=list)
    conversation: list[CodingConversationTurnModel] = Field(default_factory=list)
    interventions: list[CodingInterventionModel] = Field(default_factory=list)
    cooldown_seconds: int = 40
    last_intervention_at: datetime | None = None
    latest_reason: str | None = None
    evaluation: CodingInterviewEvaluationModel | None = None
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


class InterviewRuntimeTurnModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    stage: Literal["behavioral", "technical", "coding", "completed"]
    role: Literal["candidate", "interviewer", "system"]
    agent_name: str | None = None
    kind: Literal[
        "question",
        "followup",
        "answer",
        "hint",
        "model_answer",
        "clarification",
        "coding_reply",
        "intervention",
        "transition",
    ]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class InterviewHandoffTraceModel(BaseModel):
    from_agent: str
    to_agent: str
    stage: Literal["behavioral", "technical", "coding", "completed"]
    reason: str
    created_at: datetime = Field(default_factory=utcnow)


class InterviewDecisionTraceModel(BaseModel):
    active_agent: str
    decision_type: str
    summary: str
    stage: Literal["behavioral", "technical", "coding", "completed"]
    created_at: datetime = Field(default_factory=utcnow)


class InterviewSupportEntryModel(BaseModel):
    mode: Literal["hint", "model_answer"]
    stage: Literal["behavioral", "technical", "coding"]
    question_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=utcnow)


class InterviewBlueprintModel(BaseModel):
    role_title: str
    behavioral_goal: str
    technical_goal: str
    behavioral_target_questions: int
    technical_target_questions: int
    target_company: str | None = None
    focus_areas: list[str] = Field(default_factory=list)


class InterviewEvaluationModel(BaseModel):
    behavioral_score: int
    technical_score: int
    coding_score: int
    communication_score: int
    overall_score: int
    job_match_score: int | None = None
    behavioral_feedback: str
    technical_feedback: str
    coding_feedback: str
    communication_feedback: str
    job_match_feedback: str | None = None
    summary: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    hire_recommendation: str
    recommendation: str


class InterviewQuestionModel(BaseModel):
    id: str
    order: int
    category: Literal["behavioral", "technical"]
    prompt: str


class InterviewAnswerModel(BaseModel):
    question_id: str
    question_order: int
    category: Literal["behavioral", "technical"]
    question_prompt: str
    answer_text: str
    submitted_at: datetime = Field(default_factory=utcnow)


class InterviewQuestionFeedbackModel(BaseModel):
    question_id: str
    score: int
    feedback: str


class InterviewReportModel(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    behavioral_feedback: str
    technical_feedback: str
    communication_feedback: str
    job_match_score: int | None = None
    job_match_feedback: str | None = None
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    recommendation: str
    question_feedback: list[InterviewQuestionFeedbackModel] = Field(default_factory=list)
    coding_feedback: str = ""
    coding_evaluation: CodingInterviewEvaluationModel | None = None
    hire_recommendation: str = ""


class InterviewSessionModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID | None = None
    company_id: UUID | None = None
    company_name: str | None = None
    company_context: str | None = None
    resume_link: str | None = None
    resume_text: str | None = None
    proceed_without_resume: bool = False
    job_description_link: str | None = None
    job_description_text: str | None = None
    proceed_without_job_description: bool = False
    transcript: str | None = None
    interview_length: str | None = None
    role_title: str | None = None
    target_company: str | None = None
    voice_enabled: bool = False
    preferred_language: str = "typescript"
    coding_difficulty: str = "medium"
    interviewer_mode: str = "neutral"
    current_stage: Literal["behavioral", "technical", "coding", "completed"] = "behavioral"
    active_agent: str | None = None
    interview_blueprint: InterviewBlueprintModel | None = None
    current_prompt: InterviewRuntimeTurnModel | None = None
    turn_log: list[InterviewRuntimeTurnModel] = Field(default_factory=list)
    handoff_history: list[InterviewHandoffTraceModel] = Field(default_factory=list)
    decision_trace: list[InterviewDecisionTraceModel] = Field(default_factory=list)
    support_history: list[InterviewSupportEntryModel] = Field(default_factory=list)
    questions: list[InterviewQuestionModel] = Field(default_factory=list)
    answers: list[InterviewAnswerModel] = Field(default_factory=list)
    current_question_index: int = 0
    coding_round: CodingInterviewRoundModel | None = None
    evaluation: InterviewEvaluationModel | None = None
    score: int | None = None
    report: InterviewReportModel | None = None
    is_completed: bool = False
    practice_duration_seconds: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


class RuntimeSessionRecordRequest(BaseModel):
    record: InterviewSessionModel


class RuntimeSessionTurnRequest(BaseModel):
    turn: InterviewRuntimeTurnModel


class RuntimeSetActiveAgentRequest(BaseModel):
    active_agent: str


class RuntimeHandoffRequest(BaseModel):
    handoff: InterviewHandoffTraceModel


class RuntimeDecisionTraceRequest(BaseModel):
    decision: InterviewDecisionTraceModel


class RuntimeStageTransitionRequest(BaseModel):
    stage: Literal["behavioral", "technical", "coding", "completed"]
    reason: str
    prompt: InterviewRuntimeTurnModel | None = None


class RuntimePromptRequest(BaseModel):
    prompt: InterviewRuntimeTurnModel


class RuntimeSupportRequest(BaseModel):
    entry: InterviewSupportEntryModel


class RuntimeCodingProblemRequest(BaseModel):
    coding_round: CodingInterviewRoundModel


class RuntimeCodingEventRequest(BaseModel):
    event: CodingInterviewEventModel
    code: str = ""
    language: str | None = None
    transcript_append: str = ""


class RuntimeCodingMessageRequest(BaseModel):
    turn: CodingConversationTurnModel


class RuntimeFinalEvaluationRequest(BaseModel):
    evaluation: InterviewEvaluationModel
    report: InterviewReportModel | None = None


class RuntimeCompleteSessionRequest(BaseModel):
    report: InterviewReportModel
    evaluation: InterviewEvaluationModel | None = None
