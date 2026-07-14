"""Super-admin management API.

Post-identity-cutover state
---------------------------

Users and tenants now live in the `klaser-identity` service — this
backend no longer owns those tables. Auth-related writes have moved:

  - `POST /admin/users` (invite) → calls identity's `/api/service/users`
    via `identity_service.invite_user`. Identity issues the token,
    emails the invite, and stores the row.

Auth-related writes still pending an identity endpoint are temporarily
disabled (501). They come back once identity grows a matching write:

  - `POST /admin/users/{id}/resend-invite`
  - `PATCH /admin/users/{id}` (role/display_name/tenant/super-admin)
  - `DELETE /admin/users/{id}`
  - `POST /admin/tenants` (create tenant)

Reads (`GET /admin/tenants`, `GET /admin/users`, `GET
/admin/tenants/{id}`, `GET /admin/debug-queue`, `PATCH
/admin/tenants/{id}/system-context`) still hit this backend's local
DB — the migration seeded those tables and they're kept as a read
snapshot during the transition. The system-context patch also stays
local because the LLM reads it from here.

Everything here requires is_super_admin, enforced via the identity
introspect response. The frontend refuses to open the admin panel while
viewing another tenant.
"""
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chunk, Document, Query, Tenant, User
from app.services.identity import (
    IdentityUser,
    current_user,
    identity_service,
)

log = structlog.get_logger()
router = APIRouter()

VALID_SEGMENTS = {"kibbutz_shitufi", "kibbutz_mitchadesh", "moshav"}
VALID_ROLES = {"admin", "reviewer", "secretary"}


def _require_super_admin(user: IdentityUser = Depends(current_user)) -> IdentityUser:
    if not user.is_super_admin:
        raise HTTPException(403, "Super-admin only")
    return user


# ─────────────────────────────────────────────────────────────────────────
# Tenants
# ─────────────────────────────────────────────────────────────────────────


class TenantStats(BaseModel):
    id: str
    name: str
    segment: str
    user_count: int
    document_count: int
    created_at: str


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1)
    segment: str


@router.get("/tenants", response_model=list[TenantStats])
def list_tenants_with_stats(
    _: IdentityUser = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> list[TenantStats]:
    """List every tenant with headline counts. Powers the admin dashboard.
    Reads from this backend's local snapshot of the tenants table
    (populated by the identity migration + kept in sync manually during
    the transition). New tenants created after cutover won't appear until
    admin tenant-creation is rewired through identity."""
    user_counts = dict(
        db.execute(
            select(User.tenant_id, func.count(User.id)).group_by(User.tenant_id)
        ).all()
    )
    doc_counts = dict(
        db.execute(
            select(Document.tenant_id, func.count(Document.id)).group_by(
                Document.tenant_id
            )
        ).all()
    )
    rows = db.query(Tenant).order_by(Tenant.name).all()
    return [
        TenantStats(
            id=str(t.id),
            name=t.name,
            segment=t.segment,
            user_count=int(user_counts.get(t.id, 0)),
            document_count=int(doc_counts.get(t.id, 0)),
            created_at=t.created_at.isoformat() if t.created_at else "",
        )
        for t in rows
    ]


class TenantContext(BaseModel):
    id: str
    name: str
    segment: str
    # None when tenant has no override; the answerer falls through to the
    # generic template built from tenant name.
    system_context: str | None


class UpdateTenantContextRequest(BaseModel):
    system_context: str | None


@router.get("/tenants/{tenant_id}", response_model=TenantContext)
def get_tenant(
    tenant_id: str,
    _: IdentityUser = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> TenantContext:
    try:
        tid = UUID(tenant_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Invalid tenant_id") from e
    t = db.get(Tenant, tid)
    if t is None:
        raise HTTPException(404, "Tenant not found")
    return TenantContext(
        id=str(t.id),
        name=t.name,
        segment=t.segment,
        system_context=t.system_context,
    )


@router.patch("/tenants/{tenant_id}/system-context", response_model=TenantContext)
def update_tenant_system_context(
    tenant_id: str,
    req: UpdateTenantContextRequest,
    _: IdentityUser = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> TenantContext:
    """Update the tenant's system_context override — kept local because
    the LLM reads it directly from this backend's tenants table at
    answer time. Identity's copy stays authoritative for its own reads
    but isn't the source of truth for the LLM prompt yet."""
    try:
        tid = UUID(tenant_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Invalid tenant_id") from e
    t = db.get(Tenant, tid)
    if t is None:
        raise HTTPException(404, "Tenant not found")
    val = (req.system_context or "").strip()
    t.system_context = val if val else None
    db.commit()
    log.info(
        "admin.tenant_context_updated",
        tenant_id=str(t.id),
        length=len(val),
    )
    return TenantContext(
        id=str(t.id),
        name=t.name,
        segment=t.segment,
        system_context=t.system_context,
    )


@router.post("/tenants", response_model=TenantStats, status_code=201)
def create_tenant(
    req: CreateTenantRequest,
    _: IdentityUser = Depends(_require_super_admin),
) -> TenantStats:
    """Blocked during the identity transition — creating a tenant here
    would write only to this backend's snapshot, not to identity, so
    users invited into it wouldn't be able to log in.

    Workaround: create tenants via a direct `POST /api/service/tenants`
    call to identity once that endpoint exists (TODO), or seed via SQL
    on the identity DB.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "יצירת ארגונים מהפאנל מושבתת זמנית עד לחיבור מלא לשירות "
            "הזהויות. פנה לצוות הפיתוח."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────────────────


class UserItem(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    is_super_admin: bool
    tenant_id: str
    tenant_name: str | None = None
    created_at: str
    has_password: bool = False


class AddUserRequest(BaseModel):
    tenant_id: str
    email: str = Field(min_length=3)
    role: str = "reviewer"
    display_name: str | None = None
    is_super_admin: bool = False


class UpdateUserRequest(BaseModel):
    role: str | None = None
    display_name: str | None = None
    is_super_admin: bool | None = None
    tenant_id: str | None = None


def _user_to_item(u: User, tenant_name: str | None) -> UserItem:
    return UserItem(
        id=str(u.id),
        email=u.email,
        display_name=u.display_name,
        role=u.role,
        is_super_admin=bool(u.is_super_admin),
        tenant_id=str(u.tenant_id),
        tenant_name=tenant_name,
        has_password=u.password_hash is not None,
        created_at=u.created_at.isoformat() if u.created_at else "",
    )


@router.get("/users", response_model=list[UserItem])
def list_users(
    tenant_id: str | None = None,
    _: IdentityUser = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> list[UserItem]:
    """List users across tenants. Reads from this backend's local users
    snapshot (populated by the identity migration)."""
    q = db.query(User)
    if tenant_id:
        try:
            tid = UUID(tenant_id)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, "Invalid tenant_id") from e
        q = q.filter(User.tenant_id == tid)
    users = q.order_by(User.email).all()
    tenants = {t.id: t.name for t in db.query(Tenant).all()}
    return [_user_to_item(u, tenants.get(u.tenant_id)) for u in users]


@router.post("/users", response_model=UserItem, status_code=201)
def add_user(
    req: AddUserRequest,
    me: IdentityUser = Depends(_require_super_admin),
) -> UserItem:
    """Invite a new user via the identity service.

    Identity creates the User row, issues a registration token, and
    emails the invite. No writes to this backend's local users snapshot —
    the snapshot will pick up the new row on the next manual sync (or
    once /admin/users is rewired to read from identity)."""
    if req.role not in VALID_ROLES:
        raise HTTPException(400, f"Invalid role. Allowed: {sorted(VALID_ROLES)}")
    # is_super_admin isn't supported on invite yet — identity handles it
    # via a separate `PATCH` we haven't wired here. Fail loudly rather
    # than silently drop the flag.
    if req.is_super_admin:
        raise HTTPException(
            400,
            "הרשאת super-admin לא נתמכת בהזמנה — יש להעניק ידנית לאחר יצירה.",
        )
    try:
        UUID(req.tenant_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Invalid tenant_id") from e

    email = req.email.lower().strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, f"Invalid email: {email!r}")

    try:
        created = identity_service.invite_user(
            email=email,
            tenant_id=req.tenant_id,
            role=req.role,
            display_name=req.display_name,
            invited_by=me.display_name or me.email,
        )
    except Exception as e:
        # Bubble up identity's error to the admin panel so they see why
        # the invite failed (409 on existing email, 404 on unknown
        # tenant, etc).
        log.warning("admin.invite_via_identity_failed", error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"שגיאה בהזמנה מול שירות הזהויות: {e}",
        ) from e

    log.info(
        "admin.user_invited_via_identity",
        user_id=created.get("id"),
        email=email,
        tenant_id=req.tenant_id,
        role=req.role,
    )
    return UserItem(
        id=created["id"],
        email=created["email"],
        display_name=created.get("display_name"),
        role=created["role"],
        is_super_admin=bool(created.get("is_super_admin", False)),
        tenant_id=created["tenant_id"],
        tenant_name=None,  # identity's invite response doesn't include tenant name
        has_password=False,  # newly invited — no password yet
        created_at="",  # identity's invite response doesn't include created_at
    )


@router.post("/users/{user_id}/resend-invite")
def resend_invite(
    user_id: str,
    _: IdentityUser = Depends(_require_super_admin),
) -> dict:
    """Blocked during the identity transition — resending requires an
    identity endpoint that re-issues a registration token for an
    existing user. Workaround for now: create the account fresh under a
    different email, or ask the user to run forgot-password once they
    have any password set."""
    raise HTTPException(
        status_code=501,
        detail=(
            "שליחת הזמנה מחדש מושבתת זמנית עד לחיבור מלא לשירות "
            "הזהויות."
        ),
    )


@router.patch("/users/{user_id}", response_model=UserItem)
def update_user(
    user_id: str,
    req: UpdateUserRequest,
    request: Request,
    me: IdentityUser = Depends(_require_super_admin),
) -> UserItem:
    """Blocked during the identity transition — updating a user here
    would drift from identity. Workaround: run SQL against identity DB
    directly, or wait for the identity update endpoint."""
    raise HTTPException(
        status_code=501,
        detail=(
            "עדכון משתמשים מהפאנל מושבת זמנית עד לחיבור מלא לשירות "
            "הזהויות."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# Debug queue — queries flagged as broken by end-users
# ─────────────────────────────────────────────────────────────────────────


class DebugChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_filename: str
    section_path: str | None
    text: str


class DebugQueueItem(BaseModel):
    query_id: str
    tenant_id: str
    tenant_name: str | None
    question: str
    answer: str | None
    confidence: str | None
    llm_used: bool
    created_at: str
    retrieval_debug: dict | None
    source_chunks: list[DebugChunk]


@router.get("/debug-queue", response_model=list[DebugQueueItem])
def debug_queue(
    tenant_id: str | None = None,
    limit: int = 50,
    _: IdentityUser = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> list[DebugQueueItem]:
    """Queries the end-user flagged as broken. Reads Query + Chunk +
    Document from this backend's DB (all Takanon-owned domain data),
    and enriches tenant names from the local tenant snapshot."""
    if limit < 1 or limit > 200:
        raise HTTPException(400, "limit must be between 1 and 200")

    q = db.query(Query).filter(
        Query.feedback == "negative",
        Query.failure_mode == "retrieval_miss",
    )
    if tenant_id:
        try:
            tid = UUID(tenant_id)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, "Invalid tenant_id") from e
        q = q.filter(Query.tenant_id == tid)
    rows = q.order_by(Query.created_at.desc()).limit(limit).all()

    tenants = {t.id: t.name for t in db.query(Tenant).all()}

    all_chunk_ids: set[UUID] = set()
    for r in rows:
        for cid in r.source_chunk_ids or []:
            all_chunk_ids.add(cid)

    chunk_rows = (
        db.query(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .filter(Chunk.id.in_(all_chunk_ids))
        .all()
        if all_chunk_ids
        else []
    )
    chunk_lookup: dict[UUID, tuple[Chunk, Document]] = {
        c.id: (c, d) for c, d in chunk_rows
    }

    result: list[DebugQueueItem] = []
    for r in rows:
        chunks: list[DebugChunk] = []
        for cid in r.source_chunk_ids or []:
            pair = chunk_lookup.get(cid)
            if pair is None:
                continue
            c, d = pair
            chunks.append(
                DebugChunk(
                    chunk_id=str(c.id),
                    document_id=str(d.id),
                    document_filename=d.filename,
                    section_path=c.section_path,
                    text=c.text,
                )
            )
        result.append(
            DebugQueueItem(
                query_id=str(r.id),
                tenant_id=str(r.tenant_id),
                tenant_name=tenants.get(r.tenant_id),
                question=r.question,
                answer=r.answer,
                confidence=r.confidence,
                llm_used=bool(r.llm_used),
                created_at=r.created_at.isoformat() if r.created_at else "",
                retrieval_debug=r.retrieval_debug,
                source_chunks=chunks,
            )
        )
    return result


@router.post("/debug-queue/{query_id}/dismiss")
def dismiss_debug_item(
    query_id: str,
    _: IdentityUser = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Remove a query from the debug queue after diagnosis."""
    try:
        qid = UUID(query_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Invalid query_id") from e
    q = db.get(Query, qid)
    if q is None:
        raise HTTPException(404, "Query not found")
    q.failure_mode = None
    q.reviewer_action = "rejected"
    db.commit()
    return {"status": "ok"}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    me: IdentityUser = Depends(_require_super_admin),
) -> dict:
    """Blocked during the identity transition — deleting here would
    leave the user in identity, still able to log in. Workaround: run
    SQL against identity DB directly."""
    raise HTTPException(
        status_code=501,
        detail=(
            "מחיקת משתמשים מהפאנל מושבתת זמנית עד לחיבור מלא לשירות "
            "הזהויות."
        ),
    )
