from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.orchestrations import HandoffBuilder
import os

def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value

MARKITDOWN_MCP_URL = require_env("MCP_MARKITDOWN_HTTP") + "/mcp"
INTERVIEWDATA_MCP_URL = require_env("INTERVIEW_DATA_HTTP") + "/interview-data/mcp"

async def build_workflow_agent(chat_client):
    markitdown = MCPStreamableHTTPTool(
        name="markitdown",
        url=MARKITDOWN_MCP_URL,
    )
    
    interview_data = MCPStreamableHTTPTool(
        name="interview_data",
        url=INTERVIEWDATA_MCP_URL,
    )

    await markitdown.connect()
    await interview_data.connect()

    triage = Agent(
        client=chat_client,
        name="triage",
        instructions=(
            "You are the routing agent for an interview coach system. "
            "Do not interview the user yourself. "
            "Your job is to decide which specialist should take over next. "
            "Route to receptionist when the user needs session setup, resume parsing, "
            "or job-description intake. "
            "Route to behavioral for behavioral interview questions. "
            "Route to technical for technical interview questions. "
            "Route to summarizer when the interview is complete and the user wants feedback. "
            "If a specialist gets off-track, they may hand back to you for re-routing."
        ),
    )

    receptionist = Agent(
        client=chat_client,
        name="receptionist",
        instructions=(
            "You are the receptionist for an interview coach. "
            "Create or resume the interview session, collect the candidate resume "
            "and target job description, and prepare the interview context. "
            "Use MarkItDown tools to parse uploaded resume/job-description documents. "
            "Use InterviewData tools to create and update session state. "
            "When intake is complete, hand off to the behavioral interviewer."
        ),
        tools=[markitdown, interview_data],
    )

    behavioral = Agent(
        client=chat_client,
        name="behavioral",
        instructions=(
            "You are a behavioral interviewer. "
            "Ask STAR-method questions tailored to the candidate's background. "
            "Use InterviewData tools to read session context and store answers. "
            "Ask one question at a time. "
            "When the behavioral portion is done, hand off to the technical interviewer. "
            "If the user asks for setup help or changes topic unexpectedly, hand back to triage."
        ),
        tools=[interview_data],
    )

    technical = Agent(
        client=chat_client,
        name="technical",
        instructions=(
            "You are a technical interviewer. "
            "Ask role-specific technical questions based on the stored resume and job description. "
            "Use InterviewData tools to read session state and save the candidate's answers. "
            "Ask one question at a time. "
            "When the technical round is complete, hand off to the summarizer. "
            "If the conversation goes off-path, hand back to triage."
        ),
        tools=[interview_data],
    )
    
    summarizer = Agent(
        client=chat_client,
        name="summarizer",
        instructions=(
            "You are the interview summarizer. "
            "Use InterviewData tools to review the full session and generate a final assessment. "
            "Summarize strengths, weaknesses, behavioral performance, technical performance, "
            "and 3-5 concrete improvement suggestions. "
            "After delivering the summary, hand back to triage."
        ),
        tools=[interview_data],
    )

    workflow = (
        HandoffBuilder(
            name="interview_coach_handoff",
            participants=[triage, receptionist, behavioral, technical, summarizer],
        )
        .with_start_agent(triage)
        .add_handoff(triage, [receptionist, behavioral, technical, summarizer])
        .add_handoff(receptionist, [behavioral, triage])
        .add_handoff(behavioral, [technical, triage])
        .add_handoff(technical, [summarizer, triage])
        .add_handoff(summarizer, [triage])
        .build()
    )

    workflow_agent = workflow.as_agent(name="Interview Coach")
    return workflow_agent