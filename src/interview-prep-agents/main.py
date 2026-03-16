import os
import uuid
from typing import Dict, Tuple
from agents import build_workflow_agent
import logging
import fastapi
import fastapi.responses
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from agent_framework.openai import OpenAIChatClient
from agent_framework.ag_ui import add_agent_framework_fastapi_endpoint
from contextlib import asynccontextmanager
import sys

uploaded_files: Dict[str, Tuple[bytes, str, str]] = {}
allowed_extensions = {".pdf", ".docx", ".doc", ".txt", ".md", ".html"}

github_token = os.getenv("GITHUB_MODELS_TOKEN")
github_model = os.getenv("GITHUB_MODELS_MODEL", "openai/gpt-4.1")

if not github_token:
    raise RuntimeError("GITHUB_MODELS_TOKEN is required")

workflow_agent = None
client = None

async def startup():
    global workflow_agent
    global client
    
    client = OpenAIChatClient(
        api_key=github_token,
        model_id=github_model,
        base_url="https://models.github.ai/inference",
        default_headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": os.getenv("GITHUB_MODELS_API_VERSION", "2022-11-28"),
        },
    )
    
    workflow_agent = await build_workflow_agent(client)
    add_agent_framework_fastapi_endpoint(app, workflow_agent, path="/ag-ui")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # here put code to run on startup
    await startup()
    yield
    # here put code to run on shutdown

app = FastAPI(title="Interview Coach Agent", lifespan=lifespan)

@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check():
    """Health check endpoint."""
    return "Healthy"


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=415, detail=f"File type '{ext}' is not supported.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File size exceeds 10 MB limit.")

    file_id = uuid.uuid4().hex
    content_type = file.content_type or "application/octet-stream"
    uploaded_files[file_id] = (content, content_type, file.filename)

    url = str(request.base_url).rstrip("/") + f"/uploads/{file_id}/{file.filename}"
    return JSONResponse({"url": url})


@app.get("/uploads/{file_id}/{file_name}")
async def get_upload(file_id: str, file_name: str):
    entry = uploaded_files.get(file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")

    content, content_type, original_name = entry
    headers = {"Content-Disposition": f'inline; filename="{original_name}"'}
    return Response(content=content, media_type=content_type, headers=headers)