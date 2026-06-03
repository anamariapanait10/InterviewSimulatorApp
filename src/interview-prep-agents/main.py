from typing import Any
import fastapi
import fastapi.responses
from fastapi import FastAPI
from pydantic import BaseModel, Field

from workflow import (
    build_coding_reply_with_agent,
    build_interview_help_with_agent,
    build_interview_plan_with_agent,
    build_interview_report_with_agent,
    evaluate_coding_round_with_agent,
)
from upload_routes import router as upload_router

class InterviewPlanQuestion(BaseModel):
    id: str
    category: str
    prompt: str


class InterviewPlanRequest(BaseModel):
    resume_text: str = Field(min_length=1)
    job_description_text: str = Field(min_length=1)
    interview_length: str = Field(min_length=1)
    behavioral_count: int = Field(ge=1, le=12)
    technical_count: int = Field(ge=1, le=12)


class InterviewPlanResponse(BaseModel):
    role_title: str
    questions: list[InterviewPlanQuestion]


class InterviewAnswerPayload(BaseModel):
    question_id: str
    question_order: int
    category: str
    question_prompt: str
    answer_text: str
    submitted_at: str | None = None


class InterviewReportQuestionFeedback(BaseModel):
    question_id: str
    score: int
    feedback: str


class InterviewReportRequest(BaseModel):
    resume_text: str = Field(min_length=1)
    job_description_text: str = Field(min_length=1)
    interview_length: str = Field(min_length=1)
    role_title: str = Field(min_length=1)
    questions: list[InterviewPlanQuestion] = Field(default_factory=list)
    answers: list[InterviewAnswerPayload] = Field(default_factory=list)
    coding_feedback_input: str | None = None
    coding_hire_recommendation: str | None = None


class InterviewReportResponse(BaseModel):
    score: int
    summary: str
    strengths: list[str]
    improvements: list[str]
    behavioral_feedback: str
    technical_feedback: str
    communication_feedback: str
    recommendation: str
    question_feedback: list[InterviewReportQuestionFeedback]
    coding_feedback: str = ""
    hire_recommendation: str = ""


class InterviewHelpRequest(BaseModel):
    help_kind: str = Field(pattern="^(hint|model_answer)$")
    role_title: str = Field(min_length=1)
    question: InterviewPlanQuestion
    resume_text: str = Field(min_length=1)
    job_description_text: str = Field(min_length=1)


class InterviewHelpResponse(BaseModel):
    content: str


class CodingConversationTurnPayload(BaseModel):
    role: str
    content: str
    kind: str | None = None
    source_event_type: str | None = None
    severity: str | None = None


class CodingReplyRequest(BaseModel):
    interviewer_prompt: str = ""
    interviewer_mode: str = "neutral"
    problem_title: str = Field(min_length=1)
    problem_prompt: str = Field(min_length=1)
    problem_constraints: list[str] = Field(default_factory=list)
    problem_examples: list[dict[str, Any]] = Field(default_factory=list)
    edge_case_hints: list[str] = Field(default_factory=list)
    complexity_target: str | None = None
    recent_event_types: list[str] = Field(default_factory=list)
    transcript_recent: str = ""
    current_code: str = ""
    conversation: list[CodingConversationTurnPayload] = Field(default_factory=list)
    forced_followup: str | None = None


class CodingReplyResponse(BaseModel):
    reply: str


class CodingEvaluationRequest(BaseModel):
    problem_title: str = Field(min_length=1)
    problem_prompt: str = Field(min_length=1)
    difficulty: str = Field(min_length=1)
    language: str = Field(min_length=1)
    complexity_target: str | None = None
    current_code: str = ""
    transcript: str = ""
    conversation: list[dict[str, Any]] = Field(default_factory=list)
    event_log: list[dict[str, Any]] = Field(default_factory=list)


class CodingEvaluationResponse(BaseModel):
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

app = FastAPI(title="Interview Coach Agent")
app.include_router(upload_router)


@app.post("/interview/plan", response_model=InterviewPlanResponse)
async def build_interview_plan(payload: InterviewPlanRequest):
    parsed = await build_interview_plan_with_agent(
        resume_text=payload.resume_text,
        job_description_text=payload.job_description_text,
        interview_length=payload.interview_length,
        behavioral_count=payload.behavioral_count,
        technical_count=payload.technical_count,
    )
    return InterviewPlanResponse.model_validate(parsed)


@app.post("/interview/report", response_model=InterviewReportResponse)
async def build_interview_report(payload: InterviewReportRequest):
    parsed = await build_interview_report_with_agent(
        role_title=payload.role_title,
        interview_length=payload.interview_length,
        resume_text=payload.resume_text,
        job_description_text=payload.job_description_text,
        questions=[item.model_dump(mode="json") for item in payload.questions],
        answers=[item.model_dump(mode="json") for item in payload.answers],
        coding_feedback_input=payload.coding_feedback_input,
        coding_hire_recommendation=payload.coding_hire_recommendation,
    )
    return InterviewReportResponse.model_validate(parsed)


@app.post("/interview/help", response_model=InterviewHelpResponse)
async def build_interview_help(payload: InterviewHelpRequest):
    parsed = await build_interview_help_with_agent(
        help_kind=payload.help_kind,
        role_title=payload.role_title,
        question=payload.question.model_dump(mode="json"),
        resume_text=payload.resume_text,
        job_description_text=payload.job_description_text,
    )
    return InterviewHelpResponse.model_validate(parsed)


@app.post("/coding/reply", response_model=CodingReplyResponse)
async def build_coding_reply(payload: CodingReplyRequest):
    parsed = await build_coding_reply_with_agent(
        interviewer_prompt=payload.interviewer_prompt,
        interviewer_mode=payload.interviewer_mode,
        problem_title=payload.problem_title,
        problem_prompt=payload.problem_prompt,
        problem_constraints=payload.problem_constraints,
        problem_examples=payload.problem_examples,
        edge_case_hints=payload.edge_case_hints,
        complexity_target=payload.complexity_target,
        recent_event_types=payload.recent_event_types,
        transcript_recent=payload.transcript_recent,
        current_code=payload.current_code,
        conversation=[turn.model_dump(mode="json") for turn in payload.conversation],
        forced_followup=payload.forced_followup,
    )
    return CodingReplyResponse.model_validate(parsed)


@app.post("/coding/evaluate", response_model=CodingEvaluationResponse)
async def build_coding_evaluation(payload: CodingEvaluationRequest):
    parsed = await evaluate_coding_round_with_agent(
        problem_title=payload.problem_title,
        problem_prompt=payload.problem_prompt,
        difficulty=payload.difficulty,
        language=payload.language,
        complexity_target=payload.complexity_target,
        current_code=payload.current_code,
        transcript=payload.transcript,
        conversation=payload.conversation,
        event_log=payload.event_log,
    )
    return CodingEvaluationResponse.model_validate(parsed)

@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"
