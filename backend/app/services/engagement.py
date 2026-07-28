"""Per-tenant usage analytics — how active are a tenant's users.

Everything here reads the existing ``queries`` / ``conversations`` tables.
There is no new instrumentation: one Query row has existed per question
asked since 0001, carrying ``user_id``, ``conversation_id``,
``confidence``, ``feedback`` and ``created_at``. That means these metrics
are available retroactively over the full history, which no bolt-on
analytics tool could give us.

Two exclusions are applied by default, and both materially change the
numbers:

  * **Eval runs.** ``golden_id IS NOT NULL`` marks a golden-question test
    run issued by the eval harness, not a human. Left in, they inflate
    whichever tenant we happen to run evals against.
  * **Staff traffic.** When a super-admin tests inside a customer tenant,
    those rows carry that tenant's ``tenant_id`` and are otherwise
    indistinguishable from real engagement. Callers pass the super-admin
    user ids; ``include_staff=True`` keeps them in.

Week bucketing runs in Asia/Jerusalem and is shifted to a Sunday start.
Postgres ``date_trunc('week')`` is Monday-based (ISO), which splits an
Israeli work week across two buckets.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, case, distinct, func, literal_column, or_, select, text
from sqlalchemy.orm import Session

from app.models import Query

# A user counts as "engaged enough to have an opinion" at this many
# questions. Below it, silence is ambiguous — they may never have started.
DORMANT_MIN_QUESTIONS = 5
# Days of silence before an engaged user is flagged dormant. Deliberately
# generous: a kibbutz secretary can legitimately go weeks between bylaw
# questions, and a twitchy threshold would cry wolf every fortnight.
DORMANT_AFTER_DAYS = 21
# How many of a user's first questions count as their "first impression"
# when measuring whether refusals drove them off.
FIRST_IMPRESSION_N = 5

TZ = "Asia/Jerusalem"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _base_conditions(
    *,
    tenant_id: UUID,
    staff_ids: list[UUID] | None,
    include_staff: bool,
) -> list:
    """Filters every metric in this module shares. See module docstring."""
    conds = [Query.tenant_id == tenant_id, Query.golden_id.is_(None)]
    if not include_staff and staff_ids:
        # NULL user_id must survive the exclusion — `NOT IN` yields NULL
        # for it, which would silently drop unattributed rows and make the
        # per-user totals stop reconciling with the headline count.
        conds.append(or_(Query.user_id.is_(None), Query.user_id.notin_(staff_ids)))
    return conds


# Local wall-clock timestamp, shifted so date_trunc('week') lands on Sunday.
# (+1 day → Monday-truncate → -1 day gets us back to the Sunday boundary.)
_ONE_DAY = text("interval '1 day'")
_LOCAL_TS = func.timezone(TZ, Query.created_at)
_WEEK_START = func.date_trunc("week", _LOCAL_TS + _ONE_DAY) - _ONE_DAY


@dataclass
class TenantOverview:
    total_questions: int
    questions_30d: int
    questions_prev_30d: int
    active_users_7d: int
    active_users_30d: int
    total_conversations: int
    avg_conversation_depth: float
    refusal_rate_30d: float
    negative_feedback_30d: int
    first_question_at: datetime | None
    last_question_at: datetime | None


def tenant_overview(
    db: Session,
    *,
    tenant_id: UUID,
    staff_ids: list[UUID] | None = None,
    include_staff: bool = False,
    now: datetime | None = None,
) -> TenantOverview:
    """Headline counters for one tenant, with a prior-period comparison."""
    now = now or _now()
    d30 = now - timedelta(days=30)
    d60 = now - timedelta(days=60)
    d7 = now - timedelta(days=7)
    base = _base_conditions(
        tenant_id=tenant_id, staff_ids=staff_ids, include_staff=include_staff
    )

    row = db.execute(
        select(
            func.count(Query.id),
            func.count(Query.id).filter(Query.created_at >= d30),
            func.count(Query.id).filter(
                and_(Query.created_at >= d60, Query.created_at < d30)
            ),
            func.count(distinct(Query.user_id)).filter(Query.created_at >= d7),
            func.count(distinct(Query.user_id)).filter(Query.created_at >= d30),
            func.count(distinct(Query.conversation_id)),
            # Refusal rate is only meaningful over a recent window — a
            # lifetime figure is dominated by whatever the corpus looked
            # like at onboarding.
            func.count(Query.id).filter(
                and_(Query.created_at >= d30, Query.confidence == "refused")
            ),
            func.count(Query.id).filter(
                and_(Query.created_at >= d30, Query.feedback == "negative")
            ),
            func.min(Query.created_at),
            func.max(Query.created_at),
        ).where(*base)
    ).one()

    (
        total,
        q30,
        q_prev30,
        au7,
        au30,
        convs,
        refused30,
        neg30,
        first_at,
        last_at,
    ) = row

    # Queries predating conversations (migration 0008) have a NULL
    # conversation_id and are excluded from the distinct count, so depth is
    # computed over the conversation-era subset only.
    convo_questions = db.execute(
        select(func.count(Query.id)).where(*base, Query.conversation_id.isnot(None))
    ).scalar_one()

    return TenantOverview(
        total_questions=int(total or 0),
        questions_30d=int(q30 or 0),
        questions_prev_30d=int(q_prev30 or 0),
        active_users_7d=int(au7 or 0),
        active_users_30d=int(au30 or 0),
        total_conversations=int(convs or 0),
        avg_conversation_depth=(
            round(float(convo_questions) / float(convs), 2) if convs else 0.0
        ),
        refusal_rate_30d=(round(float(refused30) / float(q30), 4) if q30 else 0.0),
        negative_feedback_30d=int(neg30 or 0),
        first_question_at=first_at,
        last_question_at=last_at,
    )


@dataclass
class UserEngagement:
    user_id: str | None
    total_questions: int
    questions_30d: int
    first_question_at: datetime
    last_question_at: datetime
    days_since_last: int
    conversations: int
    avg_turns_per_conversation: float
    refusal_rate: float
    negative_feedback: int
    # First-impression stats: of this user's first N questions, how many
    # were refused. High here plus dormant is the churn story.
    first_impression_n: int
    first_impression_refused: int
    is_dormant: bool


def user_engagement(
    db: Session,
    *,
    tenant_id: UUID,
    staff_ids: list[UUID] | None = None,
    include_staff: bool = False,
    now: datetime | None = None,
) -> list[UserEngagement]:
    """One row per user who has ever asked something in this tenant.

    Users who were provisioned but never asked do not appear here — they
    show up in the adoption gap instead, which is computed in the route
    against identity's user list.
    """
    now = now or _now()
    d30 = now - timedelta(days=30)
    base = _base_conditions(
        tenant_id=tenant_id, staff_ids=staff_ids, include_staff=include_staff
    )

    agg = db.execute(
        select(
            Query.user_id,
            func.count(Query.id),
            func.count(Query.id).filter(Query.created_at >= d30),
            func.min(Query.created_at),
            func.max(Query.created_at),
            func.count(distinct(Query.conversation_id)),
            func.count(Query.id).filter(Query.confidence == "refused"),
            func.count(Query.id).filter(Query.feedback == "negative"),
        )
        .where(*base)
        .group_by(Query.user_id)
    ).all()

    # First-impression refusals, computed separately so the main aggregate
    # stays a plain GROUP BY. Window function ranks each user's questions
    # chronologically; we keep the first N.
    ranked = (
        select(
            Query.user_id.label("uid"),
            Query.confidence.label("confidence"),
            func.row_number()
            .over(partition_by=Query.user_id, order_by=Query.created_at.asc())
            .label("rn"),
        )
        .where(*base)
        .subquery()
    )
    first_rows = db.execute(
        select(
            ranked.c.uid,
            func.count().label("n"),
            func.sum(
                case((ranked.c.confidence == "refused", 1), else_=0)
            ).label("refused"),
        )
        .where(ranked.c.rn <= FIRST_IMPRESSION_N)
        .group_by(ranked.c.uid)
    ).all()
    first_by_uid = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in first_rows}

    out: list[UserEngagement] = []
    for uid, total, q30, first_at, last_at, convs, refused, neg in agg:
        total = int(total or 0)
        days_since = (now - last_at).days if last_at else 0
        fi_n, fi_refused = first_by_uid.get(uid, (0, 0))
        out.append(
            UserEngagement(
                user_id=str(uid) if uid else None,
                total_questions=total,
                questions_30d=int(q30 or 0),
                first_question_at=first_at,
                last_question_at=last_at,
                days_since_last=days_since,
                conversations=int(convs or 0),
                avg_turns_per_conversation=(
                    round(float(total) / float(convs), 2) if convs else 0.0
                ),
                refusal_rate=(round(float(refused) / float(total), 4) if total else 0.0),
                negative_feedback=int(neg or 0),
                first_impression_n=fi_n,
                first_impression_refused=fi_refused,
                is_dormant=(
                    total >= DORMANT_MIN_QUESTIONS
                    and days_since >= DORMANT_AFTER_DAYS
                ),
            )
        )

    # Most-dormant first — the list is meant to be read as "who has gone
    # quiet", not as a leaderboard.
    out.sort(key=lambda u: (-u.days_since_last, -u.total_questions))
    return out


@dataclass
class WeekBucket:
    week_start: datetime
    questions: int
    active_users: int
    refused: int


def weekly_activity(
    db: Session,
    *,
    tenant_id: UUID,
    weeks: int = 12,
    staff_ids: list[UUID] | None = None,
    include_staff: bool = False,
    now: datetime | None = None,
) -> list[WeekBucket]:
    """Questions and distinct askers per Sunday-start local week.

    Empty weeks are filled in with zeros — a gap in the series is the
    single most informative shape here, and letting the chart skip missing
    buckets would hide it.
    """
    now = now or _now()
    since = now - timedelta(weeks=weeks)
    base = _base_conditions(
        tenant_id=tenant_id, staff_ids=staff_ids, include_staff=include_staff
    )

    rows = db.execute(
        select(
            _WEEK_START.label("wk"),
            func.count(Query.id),
            func.count(distinct(Query.user_id)),
            func.count(Query.id).filter(Query.confidence == "refused"),
        )
        .where(*base, Query.created_at >= since)
        .group_by(literal_column("wk"))
        .order_by(literal_column("wk"))
    ).all()

    by_week = {
        (r[0].date() if hasattr(r[0], "date") else r[0]): (
            int(r[1] or 0),
            int(r[2] or 0),
            int(r[3] or 0),
        )
        for r in rows
    }

    # Build the full week spine so zero-activity weeks render as gaps.
    spine: list[WeekBucket] = []
    cursor = (now - timedelta(weeks=weeks)).date()
    # Roll back to the Sunday on or before `cursor`. Python weekday(): Mon=0..Sun=6.
    cursor = cursor - timedelta(days=(cursor.weekday() + 1) % 7)
    end = now.date()
    while cursor <= end:
        q, u, refused = by_week.get(cursor, (0, 0, 0))
        spine.append(
            WeekBucket(
                week_start=cursor,
                questions=q,
                active_users=u,
                refused=refused,
            )
        )
        cursor = cursor + timedelta(days=7)
    return spine
