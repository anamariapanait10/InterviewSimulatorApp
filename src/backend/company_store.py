from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import aiosqlite
from pydantic import BaseModel, Field


DATABASE_PATH = os.getenv("DATABASE_PATH", "./interviewcoach.db")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return utcnow()
    return datetime.fromisoformat(value)


def _parse_json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


class CompanyModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str | None = None
    website: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class CompanyKnowledgeSourceModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    title: str
    source_type: str
    content: str
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


def _row_to_company(row: aiosqlite.Row) -> CompanyModel:
    return CompanyModel(
        id=UUID(row["id"]),
        name=row["name"],
        description=row["description"],
        website=row["website"],
        created_at=_parse_datetime(row["created_at"]),
    )


def _row_to_source(row: aiosqlite.Row) -> CompanyKnowledgeSourceModel:
    return CompanyKnowledgeSourceModel(
        id=UUID(row["id"]),
        company_id=UUID(row["company_id"]),
        title=row["title"],
        source_type=row["source_type"],
        content=row["content"],
        metadata_json=_parse_json_dict(row["metadata_json"]),
        created_at=_parse_datetime(row["created_at"]),
    )


class CompanyRepository:
    async def init_db(self) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS companies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    website TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS company_knowledge_sources (
                    id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(company_id) REFERENCES companies(id)
                )
                """
            )
            await conn.commit()

    async def list_companies(self) -> list[CompanyModel]:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM companies ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            return [_row_to_company(row) for row in rows]

    async def create_company(self, name: str, description: str | None, website: str | None) -> CompanyModel:
        company = CompanyModel(name=name.strip(), description=description, website=website)
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                INSERT INTO companies (id, name, description, website, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(company.id),
                    company.name,
                    company.description,
                    company.website,
                    company.created_at.isoformat(),
                ),
            )
            await conn.commit()
        return company

    async def get_company(self, company_id: UUID) -> CompanyModel | None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM companies WHERE id = ?", (str(company_id),))
            row = await cursor.fetchone()
            return _row_to_company(row) if row else None

    async def create_knowledge_source(
        self,
        company_id: UUID,
        title: str,
        source_type: str,
        content: str,
        metadata_json: dict | None,
    ) -> CompanyKnowledgeSourceModel:
        source = CompanyKnowledgeSourceModel(
            company_id=company_id,
            title=title.strip(),
            source_type=source_type.strip(),
            content=content,
            metadata_json=metadata_json or {},
        )
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                INSERT INTO company_knowledge_sources (
                    id, company_id, title, source_type, content, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(source.id),
                    str(source.company_id),
                    source.title,
                    source.source_type,
                    source.content,
                    json.dumps(source.metadata_json, ensure_ascii=True),
                    source.created_at.isoformat(),
                ),
            )
            await conn.commit()
        return source

    async def list_knowledge_sources(self, company_id: UUID) -> list[CompanyKnowledgeSourceModel]:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT * FROM company_knowledge_sources
                WHERE company_id = ?
                ORDER BY created_at DESC
                """,
                (str(company_id),),
            )
            rows = await cursor.fetchall()
            return [_row_to_source(row) for row in rows]

    async def get_knowledge_source(self, source_id: UUID) -> CompanyKnowledgeSourceModel | None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM company_knowledge_sources WHERE id = ?",
                (str(source_id),),
            )
            row = await cursor.fetchone()
            return _row_to_source(row) if row else None

    async def update_knowledge_source(
        self,
        source_id: UUID,
        *,
        title: str,
        source_type: str,
        content: str,
        metadata_json: dict | None,
    ) -> CompanyKnowledgeSourceModel | None:
        existing = await self.get_knowledge_source(source_id)
        if existing is None:
            return None

        updated = existing.model_copy(
            update={
                "title": title.strip(),
                "source_type": source_type.strip(),
                "content": content,
                "metadata_json": metadata_json or {},
            }
        )

        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute(
                """
                UPDATE company_knowledge_sources
                SET title = ?, source_type = ?, content = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    updated.title,
                    updated.source_type,
                    updated.content,
                    json.dumps(updated.metadata_json, ensure_ascii=True),
                    str(source_id),
                ),
            )
            await conn.commit()
        return updated

    async def delete_knowledge_source(self, source_id: UUID) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as conn:
            await conn.execute("DELETE FROM company_knowledge_sources WHERE id = ?", (str(source_id),))
            await conn.commit()
