"""User-initiated support reports from the search UI.

One endpoint: `POST /api/support/report` — user clicks "דווח בעיה" on a
turn, writes a free-form note, we email Tal with the full context
(tenant, user, transcript, deep link back to the conversation).

Fire-and-forget — mail failure never surfaces to the user. The report
is logged either way so we can reconcile with sends after the fact.
"""
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Conversation, Query
from app.services.identity import (
    IdentityUser,
    current_user,
    get_tenant_cached,
)
from app.services.mail import SupportTurnSnapshot, send_support_request

log = structlog.get_logger()
router = APIRouter()


class SupportReportRequest(BaseModel):
    query_id: UUID
    note: str = Field(default="", max_length=4000)


class SupportReportResponse(BaseModel):
    status: str


@router.post("/report", response_model=SupportReportResponse)
def report(
    req: SupportReportRequest,
    db: Session = Depends(get_db),
    user: IdentityUser = Depends(current_user),
) -> SupportReportResponse:
    q = db.get(Query, req.query_id)
    if q is None or q.tenant_id != user.tenant_id:
        raise HTTPException(404, "Query not found")

    conv: Conversation | None = None
    turns_out: list[SupportTurnSnapshot] = []
    if q.conversation_id is not None:
        conv = db.get(Conversation, q.conversation_id)
        rows = (
            db.query(Query)
            .filter(Query.conversation_id == q.conversation_id)
            .order_by(Query.turn_index.asc().nulls_last(), Query.created_at.asc())
            .all()
        )
        for r in rows:
            if r.question:
                turns_out.append(SupportTurnSnapshot(role="user", text=r.question))
            if r.answer:
                turns_out.append(SupportTurnSnapshot(role="assistant", text=r.answer))
    else:
        # Legacy Query rows without a conversation — just include the pair.
        if q.question:
            turns_out.append(SupportTurnSnapshot(role="user", text=q.question))
        if q.answer:
            turns_out.append(SupportTurnSnapshot(role="assistant", text=q.answer))

    tenant = get_tenant_cached(user.tenant_id)
    tenant_name = (tenant or {}).get("name") or "—"

    conv_id_str = str(conv.id) if conv else ""
    base_url = (settings.klaser_app_url or "").rstrip("/")
    deep_link = f"{base_url}/?c={conv_id_str}" if conv_id_str else base_url

    try:
        send_support_request(
            tenant_name=tenant_name,
            user_email=user.email,
            user_display_name=user.display_name,
            note=req.note,
            question=q.question or "",
            conversation_id=conv_id_str,
            conversation_deep_link=deep_link,
            query_id=str(q.id),
            turns=turns_out,
        )
    except Exception as e:  # pragma: no cover — _send already swallows
        log.warning("support.report_send_failed", error=str(e))

    log.info(
        "support.report",
        tenant_id=str(user.tenant_id),
        tenant_name=tenant_name,
        user_email=user.email,
        query_id=str(q.id),
        conversation_id=conv_id_str,
        note_length=len(req.note or ""),
    )
    return SupportReportResponse(status="sent")
