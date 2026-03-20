import os
import logging
import fastapi
import fastapi.responses
from fastapi import FastAPI
from agent_framework.ag_ui import AgentFrameworkAgent, add_agent_framework_fastapi_endpoint
from contextlib import asynccontextmanager

from agents import build_workflow_agent
from chat_client import build_chat_client
from opentelemetry_patch import patch_opentelemetry_detach
from thread_router import ThreadScopedAgentRouter
from upload_routes import router as upload_router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("interview-prep-agents")

workflow_agent = None
client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global workflow_agent
    global client

    client, active_provider, active_model = build_chat_client()
    patch_opentelemetry_detach()

    logger.info("Agent startup provider=%s model=%s", active_provider, active_model)
    workflow_agent = ThreadScopedAgentRouter(lambda: build_workflow_agent(client))
    agui_agent = AgentFrameworkAgent(agent=workflow_agent, require_confirmation=False)
    add_agent_framework_fastapi_endpoint(app, agui_agent, path="/ag-ui")
    logger.info("Agent startup complete")
    yield

app = FastAPI(title="Interview Coach Agent", lifespan=lifespan)
app.include_router(upload_router)

@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"


