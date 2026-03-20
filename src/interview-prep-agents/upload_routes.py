import os
import uuid
from typing import Dict, Tuple

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

allowed_extensions = {".pdf", ".docx", ".doc", ".txt", ".md", ".html"}
uploaded_files: Dict[str, Tuple[bytes, str, str]] = {}

router = APIRouter()


@router.post("/upload")
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


@router.get("/uploads/{file_id}/{file_name}")
async def get_upload(file_id: str, file_name: str):
    entry = uploaded_files.get(file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")

    content, content_type, original_name = entry
    headers = {"Content-Disposition": f'inline; filename="{original_name}"'}
    return Response(content=content, media_type=content_type, headers=headers)
