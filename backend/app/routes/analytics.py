"""Per-tenant usage analytics — super-admin only.

Answers "are this tenant's users actually using the thing": how many
questions, by whom, how often, and who has gone quiet. Everything is
derived from the existing ``queries`` table (see services/engagement.py
for the aggregation and the exclusions it applies).

Access is super-admin only, enforced with the same
``_require_super_admin`` dependency the admin panel uses. Tenant admins
and managers get a 403 — this surface compares tenants against each
other and names individual users' activity, which is ours to see and not
theirs.

Tenant selection is a ``?tenant_id=`` query param rather than the
tenant-switch mechanism, matching ``GET /admin/users``. Switching would
rewrite the caller's identity context; a read-only param lets a
super-admin compare tenants without leaving their own session.
"""
from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.routes.admin import _require_super_admin
from app.services import engagement
from app.services.identity import IdentityUser, identity_service

log = structlog.get_logger()
router = APIRouter()


class OverviewOut(BaseModel):
    total_questions: int
    questions_30d: int
    questions_prev_30d: int
    # None when there is no prior period to compare against (tenant younger
    # than 60 days) — the UI shows "—" rather than a meaningless +100%.
    trend_pct: float | None
    active_users_7d: int
    active_users_30d: int
    total_conversations: int
    avg_conversation_depth: float
    refusal_rate_30d: float
    negative_feedback_30d: int
    first_question_at: datetime | None
    last_question_at: datetime | None


class AdoptionOut(BaseModel):
    provisioned_users: int
    users_ever_asked: int
    never_asked: list[str]  # display names / emails


class UserRowOut(BaseModel):
    user_id: str | None
    display_name: str | None
    email: str | None
    role: str | None
    total_questions: int
    questions_30d: int
    first_question_at: datetime
    last_question_at: datetime
    days_since_last: int
    conversations: int
    avg_turns_per_conversation: float
    refusal_rate: float
    negative_feedback: int
    first_impression_n: int
    first_impression_refused: int
    is_dormant: bool


class WeekOut(BaseModel):
    week_start: str
    questions: int
    active_users: int
    refused: int


class AnalyticsOut(BaseModel):
    tenant_id: str
    tenant_name: str | None
    generated_at: datetime
    include_staff: bool
    dormant_after_days: int
    dormant_min_questions: int
    overview: OverviewOut
    adoption: AdoptionOut
    users: list[UserRowOut]
    weekly: list[WeekOut]


def _staff_and_directory(tenant_id: str) -> tuple[list[UUID], dict[str, dict]]:
    """Super-admin user ids (to exclude), and a tenant user directory.

    One identity round trip for all users, filtered locally — identity's
    list endpoint has no "super admins only" mode, and we need the full
    tenant roster anyway for the adoption gap.
    """
    try:
        everyone = identity_service.list_users()
    except Exception as e:
        log.warning("analytics.identity_users_failed", error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"שגיאה בשליפת משתמשים משירות הזהויות: {e}",
        ) from e

    staff_ids: list[UUID] = []
    directory: dict[str, dict] = {}
    for u in everyone:
        if u.get("is_super_admin"):
            try:
                staff_ids.append(UUID(u["id"]))
            except (ValueError, KeyError, TypeError):
                continue
        if u.get("tenant_id") == tenant_id:
            directory[u["id"]] = u
    return staff_ids, directory


@router.get("", response_model=AnalyticsOut)
def tenant_analytics(
    tenant_id: str = QueryParam(..., description="Tenant to report on"),
    weeks: int = QueryParam(12, ge=4, le=52),
    include_staff: bool = QueryParam(
        False,
        description="Include super-admin traffic. Off by default: staff "
        "testing inside a customer tenant otherwise reads as engagement.",
    ),
    _: IdentityUser = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> AnalyticsOut:
    try:
        tid = UUID(tenant_id)
    except ValueError as e:
        raise HTTPException(400, "tenant_id אינו UUID תקין") from e

    staff_ids, directory = _staff_and_directory(tenant_id)

    ov = engagement.tenant_overview(
        db, tenant_id=tid, staff_ids=staff_ids, include_staff=include_staff
    )
    users = engagement.user_engagement(
        db, tenant_id=tid, staff_ids=staff_ids, include_staff=include_staff
    )
    weekly = engagement.weekly_activity(
        db, tenant_id=tid, weeks=weeks, staff_ids=staff_ids, include_staff=include_staff
    )

    trend: float | None = None
    if ov.questions_prev_30d > 0:
        trend = round(
            (ov.questions_30d - ov.questions_prev_30d) / ov.questions_prev_30d * 100, 1
        )

    # Adoption gap: provisioned in identity but absent from the query log.
    # Staff are excluded from the denominator unless explicitly included,
    # so a tenant isn't penalised for the super-admins attached to it.
    roster = {
        uid: u
        for uid, u in directory.items()
        if include_staff or not u.get("is_super_admin")
    }
    ever_asked = {u.user_id for u in users if u.user_id}
    never_asked = [
        u.get("display_name") or u.get("email") or uid
        for uid, u in roster.items()
        if uid not in ever_asked
    ]

    tenant_name = None
    try:
        t = identity_service.get_tenant(tenant_id)
        tenant_name = t.get("name") if t else None
    except Exception:
        # Cosmetic only — the panel still works with an unnamed tenant.
        log.info("analytics.tenant_name_lookup_failed", tenant_id=tenant_id)

    return AnalyticsOut(
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        generated_at=engagement._now(),
        include_staff=include_staff,
        dormant_after_days=engagement.DORMANT_AFTER_DAYS,
        dormant_min_questions=engagement.DORMANT_MIN_QUESTIONS,
        overview=OverviewOut(
            total_questions=ov.total_questions,
            questions_30d=ov.questions_30d,
            questions_prev_30d=ov.questions_prev_30d,
            trend_pct=trend,
            active_users_7d=ov.active_users_7d,
            active_users_30d=ov.active_users_30d,
            total_conversations=ov.total_conversations,
            avg_conversation_depth=ov.avg_conversation_depth,
            refusal_rate_30d=ov.refusal_rate_30d,
            negative_feedback_30d=ov.negative_feedback_30d,
            first_question_at=ov.first_question_at,
            last_question_at=ov.last_question_at,
        ),
        adoption=AdoptionOut(
            provisioned_users=len(roster),
            users_ever_asked=len(ever_asked),
            never_asked=sorted(never_asked),
        ),
        users=[
            UserRowOut(
                user_id=u.user_id,
                display_name=(
                    directory.get(u.user_id, {}).get("display_name")
                    if u.user_id
                    else None
                ),
                email=(
                    directory.get(u.user_id, {}).get("email") if u.user_id else None
                ),
                role=directory.get(u.user_id, {}).get("role") if u.user_id else None,
                total_questions=u.total_questions,
                questions_30d=u.questions_30d,
                first_question_at=u.first_question_at,
                last_question_at=u.last_question_at,
                days_since_last=u.days_since_last,
                conversations=u.conversations,
                avg_turns_per_conversation=u.avg_turns_per_conversation,
                refusal_rate=u.refusal_rate,
                negative_feedback=u.negative_feedback,
                first_impression_n=u.first_impression_n,
                first_impression_refused=u.first_impression_refused,
                is_dormant=u.is_dormant,
            )
            for u in users
        ],
        weekly=[
            WeekOut(
                week_start=w.week_start.isoformat(),
                questions=w.questions,
                active_users=w.active_users,
                refused=w.refused,
            )
            for w in weekly
        ],
    )
