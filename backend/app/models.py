"""SQLAlchemy models — implements the schema from mvp-spec.md §3.3."""
from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import UUID as SQLUUID
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base

# Embedding dimension. 1024 for Cohere embed-multilingual-v3, 3072 for OpenAI 3-large.
# We'll commit to one after the Week 1 benchmark.
EMBED_DIM = 1024


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    segment: Mapped[str] = mapped_column(String, nullable=False)  # kibbutz_shitufi | kibbutz_mitchadesh | moshav
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("tenants.id"))
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, nullable=False)  # admin | reviewer | secretary
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    doc_type: Mapped[str | None] = mapped_column(String)  # bylaw | sub_bylaw | minutes | decision | other
    effective_date: Mapped[Date | None] = mapped_column(Date)
    superseded_by_id: Mapped[UUID | None] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("documents.id"))
    source_uri: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("documents.id"))
    tenant_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    text_search: Mapped[str | None] = mapped_column(TSVECTOR)
    chunk_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)
    effective_date: Mapped[Date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")


class Query(Base):
    __tablename__ = "queries"
    id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    user_id: Mapped[UUID | None] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    answer: Mapped[str | None] = mapped_column(Text)
    source_chunk_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(SQLUUID(as_uuid=True)))
    confidence: Mapped[str | None] = mapped_column(String)  # confident | refused | uncertain
    llm_used: Mapped[bool] = mapped_column(Boolean, default=True)
    authoritative_answer_id: Mapped[UUID | None] = mapped_column(
        SQLUUID(as_uuid=True), ForeignKey("authoritative_answers.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthoritativeAnswer(Base):
    __tablename__ = "authoritative_answers"
    id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    canonical_question: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_question_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(SQLUUID(as_uuid=True)))
    approved_by_id: Mapped[UUID | None] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    internal_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="active")  # active | retired
    similarity_threshold: Mapped[float] = mapped_column(Float, default=0.92)


class Lexicon(Base):
    __tablename__ = "lexicon"
    id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    term: Mapped[str] = mapped_column(Text, nullable=False)
    expansion: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[UUID | None] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
