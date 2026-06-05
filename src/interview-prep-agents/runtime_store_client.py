from __future__ import annotations

import os
from typing import Any

import httpx


def get_runtime_store_base_url() -> str:
    return (
        os.getenv("INTERVIEW_DATA_HTTP")
        or os.getenv("INTERVIEW_DATA_URL")
        or os.getenv("INTERVIEW_DATA_HTTPS")
        or "http://127.0.0.1:8001"
    ).rstrip("/")


async def get_json(path: str) -> dict[str, Any] | list[Any] | None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{get_runtime_store_base_url()}{path}")
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()


async def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{get_runtime_store_base_url()}{path}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"Runtime store returned invalid payload for {path}")
        return data
