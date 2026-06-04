from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHROMA_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"
COLLECTION_NAME = "company_knowledge"
EMBEDDING_MODEL = "text-embedding-3-small"

_client: Any | None = None
_collection: Any | None = None
_openai_client: Any | None = None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("The 'openai' package is required for RAG embeddings.") from exc
        _openai_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        )
    return _openai_client


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("The 'chromadb' package is required for local RAG storage.") from exc

    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    text_length = len(normalized)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        if end < text_length:
            split_candidates = [
                normalized.rfind(separator, start, end)
                for separator in (". ", "! ", "? ", "\n", "; ", ", ")
            ]
            split_at = max(split_candidates)
            if split_at > start + max(chunk_size // 3, 120):
                end = split_at + 1

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break
        start = max(end - overlap, start + 1)

    return chunks


def get_embedding(text: str) -> list[float]:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Cannot embed empty text")

    client = _get_openai_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=cleaned,
        encoding_format="float",
    )
    return list(response.data[0].embedding)


def index_company_document(
    company_id: str,
    company_name: str,
    title: str,
    content: str,
    source_type: str,
    metadata: dict[str, Any] | None,
) -> int:
    chunks = chunk_text(content)
    if not chunks:
        return 0

    collection = _get_collection()
    metadata = metadata or {}
    created_at = str(metadata.get("created_at") or _utcnow_iso())
    base_metadata = {
        "company_id": str(company_id),
        "company_name": str(company_name),
        "title": str(title),
        "source_type": str(source_type),
        "role": str(metadata.get("role") or ""),
        "category": str(metadata.get("category") or ""),
        "url": str(metadata.get("url") or ""),
        "created_at": created_at,
        "source_id": str(metadata.get("source_id") or ""),
    }

    ids: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, Any]] = []

    for index, chunk in enumerate(chunks):
        ids.append(f"{company_id}:{metadata.get('source_id') or uuid.uuid4()}:{index}")
        embeddings.append(get_embedding(chunk))
        metadatas.append({**base_metadata, "chunk_index": index})

    collection.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(chunks)


def retrieve_company_context(company_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    collection = _get_collection()
    results = collection.query(
        query_embeddings=[get_embedding(cleaned_query)],
        n_results=max(1, top_k),
        where={"company_id": str(company_id)},
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])
    metadatas = results.get("metadatas", [[]])
    distances = results.get("distances", [[]])
    rows: list[dict[str, Any]] = []

    for document, chunk_metadata, distance in zip(
        documents[0] if documents else [],
        metadatas[0] if metadatas else [],
        distances[0] if distances else [],
        strict=False,
    ):
        rows.append(
            {
                "content": document,
                "metadata": chunk_metadata or {},
                "distance": distance,
            }
        )
    return rows


def delete_company_knowledge(company_id: str) -> None:
    collection = _get_collection()
    collection.delete(where={"company_id": str(company_id)})
