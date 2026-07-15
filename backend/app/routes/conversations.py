"""Conversation endpoints — list / get for the chat sidebar + thread view.

The thread itself is reconstructed from ``queries`` rows scoped to the
conversation. Each Query row is a turn; ``confidence == "clarifying"``
identifies an assistant-asked clarification (no sources, awaiting user
reply).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Chunk, Conversation, Query
from app.services.identity import IdentityUser, current_user

router = APIRouter()


class ConversationSummary(BaseModel):
    id: UUID
    title: str | None
    created_at: str
    updated_at: str
    turn_count: int
    last_user_question: str | None
    last_assistant_answer: str | None


class TurnSource(BaseModel):
    chunk_id: UUID
    document_filename: str
    section_path: str | None


class Turn(BaseModel):
    query_id: UUID
    turn_index: int | None
    question: str
    answer: str | None
    confidence: str | None
    mode: str  # "answer" | "clarify"
    sources: list[TurnSource] = []
    feedback: str | None
    created_at: str


class ConversationDetail(BaseModel):
    id: UUID
    title: str | None
    created_at: str
    updated_at: str
    turns: list[Turn]


def _confidence_to_mode(confidence: str | None) -> str:
    return "clarify" if confidence == "clarifying" else "answer"


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
    limit: int = 30,
) -> list[ConversationSummary]:
    convs = (
        db.query(Conversation)
        .filter(Conversation.tenant_id == user.tenant_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .all()
    )
    out: list[ConversationSummary] = []
    for c in convs:
        turns = (
            db.query(Query)
            .filter(Query.conversation_id == c.id)
            .order_by(Query.turn_index.asc().nulls_last(), Query.created_at.asc())
            .all()
        )
        last_user = next((t.question for t in reversed(turns) if t.question), None)
        last_assistant = next((t.answer for t in reversed(turns) if t.answer), None)
        out.append(
            ConversationSummary(
                id=c.id,
                title=c.title or (last_user[:60] if last_user else None),
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
                turn_count=len(turns),
                last_user_question=last_user,
                last_assistant_answer=last_assistant,
            )
        )
    return out


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> ConversationDetail:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != user.tenant_id:
        # 404 (not 403) to avoid leaking other tenants' conversations.
        raise HTTPException(404, "Conversation not found")

    rows = (
        db.query(Query)
        .filter(Query.conversation_id == conv.id)
        .order_by(Query.turn_index.asc().nulls_last(), Query.created_at.asc())
        .all()
    )

    # One query per conversation for source chunks — flatten all chunk ids.
    all_chunk_ids: set[UUID] = set()
    for r in rows:
        for cid in r.source_chunk_ids or []:
            all_chunk_ids.add(cid)
    chunk_index = {}
    if all_chunk_ids:
        for c in (
            db.query(Chunk)
            .filter(Chunk.id.in_(list(all_chunk_ids)))
            .options(joinedload(Chunk.document))
            .all()
        ):
            chunk_index[c.id] = c

    turns: list[Turn] = []
    for r in rows:
        sources: list[TurnSource] = []
        for cid in r.source_chunk_ids or []:
            c = chunk_index.get(cid)
            if c is not None:
                sources.append(
                    TurnSource(
                        chunk_id=c.id,
                        document_filename=c.document.filename,
                        section_path=c.section_path,
                    )
                )
        turns.append(
            Turn(
                query_id=r.id,
                turn_index=r.turn_index,
                question=r.question,
                answer=r.answer,
                confidence=r.confidence,
                mode=_confidence_to_mode(r.confidence),
                sources=sources,
                feedback=r.feedback,
                created_at=r.created_at.isoformat(),
            )
        )

    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        turns=turns,
    )


class RenameRequest(BaseModel):
    title: str


@router.patch("/{conversation_id}")
def rename_conversation(
    conversation_id: UUID,
    req: RenameRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != user.tenant_id:
        raise HTTPException(404, "Conversation not found")
    conv.title = req.title.strip() or None
    db.commit()
    return {"status": "ok"}


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> dict:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != user.tenant_id:
        raise HTTPException(404, "Conversation not found")
    # Detach Query rows from the conversation rather than deleting them —
    # queries are part of the audit trail and the reviewer queue.
    db.query(Query).filter(Query.conversation_id == conv.id).update(
        {Query.conversation_id: None}, synchronize_session=False
    )
    db.delete(conv)
    db.commit()
    return {"status": "ok"}
