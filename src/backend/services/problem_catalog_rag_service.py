from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from coding_problem_bank import DEFAULT_CODING_PROBLEMS


CHROMA_PATH = Path(__file__).resolve().parent.parent / "data" / "problem_chroma"
COLLECTION_NAME = "coding_problem_catalog"
EMBEDDING_MODEL = "text-embedding-3-small"

_client: Any | None = None
_collection: Any | None = None
_openai_client: Any | None = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("The 'openai' package is required for problem catalog embeddings.") from exc
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
        raise RuntimeError("The 'chromadb' package is required for problem catalog RAG.") from exc

    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def _embed(text: str) -> list[float]:
    client = _get_openai_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text.strip(),
        encoding_format="float",
    )
    return list(response.data[0].embedding)


def _problem_document(problem: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in [
            str(problem.get("company") or ""),
            str(problem.get("title") or ""),
            str(problem.get("difficulty") or ""),
            str(problem.get("prompt") or ""),
            " ".join(problem.get("expected_topics") or []),
            " ".join(problem.get("style_tags") or []),
            " ".join(problem.get("constraints") or []),
            str(problem.get("complexity_target") or ""),
        ]
        if part
    ).strip()


def index_problem_catalog() -> int:
    collection = _get_collection()

    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, Any]] = []

    for raw_problem in DEFAULT_CODING_PROBLEMS:
        problem_id = str(raw_problem["id"])
        document = _problem_document(raw_problem)
        ids.append(problem_id)
        documents.append(document)
        embeddings.append(_embed(document))
        metadatas.append(
            {
                "problem_id": problem_id,
                "title": str(raw_problem.get("title") or ""),
                "company": str(raw_problem.get("company") or ""),
                "difficulty": str(raw_problem.get("difficulty") or ""),
                "expected_topics": ", ".join(raw_problem.get("expected_topics") or []),
                "style_tags": ", ".join(raw_problem.get("style_tags") or []),
                "complexity_target": str(raw_problem.get("complexity_target") or ""),
            }
        )

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(ids)


def search_problem_catalog(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    collection = _get_collection()
    results = collection.query(
        query_embeddings=[_embed(cleaned_query)],
        n_results=max(1, top_k),
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])
    metadatas = results.get("metadatas", [[]])
    distances = results.get("distances", [[]])
    rows: list[dict[str, Any]] = []

    for document, metadata, distance in zip(
        documents[0] if documents else [],
        metadatas[0] if metadatas else [],
        distances[0] if distances else [],
        strict=False,
    ):
        rows.append(
            {
                "content": document,
                "metadata": metadata or {},
                "distance": distance,
            }
        )

    return rows
