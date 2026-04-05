import os
import json
import logging
import fastapi
import fastapi.responses
from fastapi import FastAPI
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from agents import Agent, Runner

from workflow import run_text_turn, initialize_mcp_servers, cleanup_mcp_servers
from upload_routes import router as upload_router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("interview-prep-agents")

for key, value in os.environ.items():
    logger.info("Env var %s=%s", key, value)


class ChatInputMessage(BaseModel):
    role: str
    content: str


class ChatStreamRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    history: list[ChatInputMessage] = Field(default_factory=list)


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


def _to_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _strip_json_fence(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
        if candidate.endswith("```"):
            candidate = candidate[:-3]
    return candidate.strip()


async def _run_structured_prompt(*, name: str, instructions: str, prompt: str) -> dict:
    agent = Agent(name=name, instructions=instructions, model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    result = await Runner.run(agent, input=prompt)
    final_output = getattr(result, "final_output", "")
    if isinstance(final_output, str):
        text = final_output
    elif final_output is None:
        text = ""
    else:
        text = str(final_output)

    parsed = json.loads(_strip_json_fence(text))
    if not isinstance(parsed, dict):
        raise RuntimeError("Model did not return a JSON object")
    return parsed

@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_mcp_servers()
    logger.info("OpenAI agent runtime startup complete")
    try:
        yield
    finally:
        await cleanup_mcp_servers()

app = FastAPI(title="Interview Coach Agent", lifespan=lifespan)
app.include_router(upload_router)


@app.post("/chat/stream")
async def stream_chat(payload: ChatStreamRequest):
    async def event_generator():
        yield _to_sse({"type": "start", "sessionId": payload.session_id})
        try:
            answer = await run_text_turn(
                message=payload.message,
                history=[m.model_dump() for m in payload.history],
                session_id=payload.session_id,
            )
            if answer:
                yield _to_sse({"type": "delta", "delta": answer})
            yield _to_sse({"type": "done"})
        except Exception as exc:
            logger.exception("text turn failed")
            yield _to_sse({"type": "error", "error": str(exc) or "Agent execution failed"})

    return fastapi.responses.StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/interview/plan", response_model=InterviewPlanResponse)
async def build_interview_plan(payload: InterviewPlanRequest):
    prompt = f"""
Create a complete interview plan as strict JSON.

Interview length: {payload.interview_length}
Behavioral questions required: {payload.behavioral_count}
Technical questions required: {payload.technical_count}

Resume:
{payload.resume_text}

Job description:
{payload.job_description_text}

Return JSON with this exact shape:
{{
  "role_title": "short role title",
  "questions": [
    {{"id": "behavioral-1", "category": "behavioral", "prompt": "..."}} ,
    {{"id": "technical-1", "category": "technical", "prompt": "..."}}
  ]
}}

Rules:
- Return exactly {payload.behavioral_count + payload.technical_count} questions.
- The first {payload.behavioral_count} must be behavioral.
- The remaining {payload.technical_count} must be technical.
- Each question must be tailored to the candidate and role.
- Do not wrap the JSON in markdown fences.
""".strip()

    parsed = await _run_structured_prompt(
        name="interview_planner",
        instructions=(
            "You create tailored interview plans. "
            "Return only valid JSON that matches the user's requested schema."
        ),
        prompt=prompt,
    )
    return InterviewPlanResponse.model_validate(parsed)


@app.post("/interview/report", response_model=InterviewReportResponse)
async def build_interview_report(payload: InterviewReportRequest):
    prompt = f"""
Evaluate the completed interview and return strict JSON only.

Role title: {payload.role_title}
Interview length: {payload.interview_length}

Resume:
{payload.resume_text}

Job description:
{payload.job_description_text}

Questions:
{json.dumps([item.model_dump(mode="json") for item in payload.questions], ensure_ascii=True, indent=2)}

Answers:
{json.dumps([item.model_dump(mode="json") for item in payload.answers], ensure_ascii=True, indent=2)}

Return JSON with this exact shape:
{{
  "score": 82,
  "summary": "2-3 sentence summary",
  "strengths": ["...", "...", "..."],
  "improvements": ["...", "...", "..."],
  "behavioral_feedback": "...",
  "technical_feedback": "...",
  "communication_feedback": "...",
  "recommendation": "...",
  "question_feedback": [
    {{"question_id": "behavioral-1", "score": 8, "feedback": "..."}}
  ]
}}

Rules:
- Score must be an integer from 1 to 100.
- Include one question_feedback item per answer.
- Keep strengths and improvements concrete and actionable.
- Do not wrap the JSON in markdown fences.
""".strip()

    parsed = await _run_structured_prompt(
        name="interview_evaluator",
        instructions=(
            "You evaluate mock interviews and return only strict JSON. "
            "Be specific, fair, and pragmatic."
        ),
        prompt=prompt,
    )
    return InterviewReportResponse.model_validate(parsed)

@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"


