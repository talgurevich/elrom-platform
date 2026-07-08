"""Super-admin management API.

Everything here requires is_super_admin. Provides tenant creation, per-tenant
user CRUD, and grant/revoke super-admin — replacing the previous CLI-only
flow (scripts/create_tenant.py, scripts/add_user.py, scripts/grant_super_admin.py).

Note: none of these routes are gated by the switch-mode read-only middleware
because they're the super-admin's own control surface, not a tenant's data.
The super-admin should perform these actions from their home tenant (not while
"viewing" a customer). The frontend enforces that by refusing to open the
admin panel while viewing_other_tenant is true.
"""
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chunk, Document, Query, Tenant, User
from app.routes.auth import current_user
from app.services.mail import send_invite

log = structlog.get_logger()
router = APIRouter()

VALID_SEGMENTS = {"kibbutz_shitufi", "kibbutz_mitchadesh", "moshav"}
VALID_ROLES = {"admin", "reviewer", "secretary"}


def _require_super_admin(user: User = Depends(current_user)) -> User:
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
    _: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> list[TenantStats]:
    """List every tenant with headline counts. Powers the admin dashboard."""
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


@router.post("/tenants", response_model=TenantStats, status_code=201)
def create_tenant(
    req: CreateTenantRequest,
    _: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> TenantStats:
    if req.segment not in VALID_SEGMENTS:
        raise HTTPException(400, f"Invalid segment. Allowed: {sorted(VALID_SEGMENTS)}")
    name = req.name.strip()
    if db.query(Tenant).filter(Tenant.name == name).first():
        raise HTTPException(409, f"Tenant with name {name!r} already exists")
    t = Tenant(name=name, segment=req.segment)
    db.add(t)
    db.commit()
    db.refresh(t)
    log.info("admin.tenant_created", tenant_id=str(t.id), name=name)
    return TenantStats(
        id=str(t.id),
        name=t.name,
        segment=t.segment,
        user_count=0,
        document_count=0,
        created_at=t.created_at.isoformat() if t.created_at else "",
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
    tenant_id: str | None = None  # allow moving a user between tenants


def _user_to_item(u: User, tenant_name: str | None) -> UserItem:
    return UserItem(
        id=str(u.id),
        email=u.email,
        display_name=u.display_name,
        role=u.role,
        is_super_admin=bool(u.is_super_admin),
        tenant_id=str(u.tenant_id),
        tenant_name=tenant_name,
        created_at=u.created_at.isoformat() if u.created_at else "",
    )


@router.get("/users", response_model=list[UserItem])
def list_users(
    tenant_id: str | None = None,
    _: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> list[UserItem]:
    """List users across all tenants. Optionally filter by tenant_id."""
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
    background_tasks: BackgroundTasks,
    me: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> UserItem:
    if req.role not in VALID_ROLES:
        raise HTTPException(400, f"Invalid role. Allowed: {sorted(VALID_ROLES)}")
    try:
        tid = UUID(req.tenant_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Invalid tenant_id") from e
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")
    email = req.email.lower().strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, f"Invalid email: {email!r}")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, f"User with email {email!r} already exists")
    u = User(
        tenant_id=tid,
        email=email,
        display_name=req.display_name,
        role=req.role,
        is_super_admin=req.is_super_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    log.info(
        "admin.user_created",
        user_id=str(u.id),
        email=email,
        tenant=tenant.name,
        role=u.role,
        super_admin=u.is_super_admin,
    )

    # Fire welcome/invite email in the background so a slow SMTP hop doesn't
    # delay the admin's create-user request. send_invite is no-raising.
    background_tasks.add_task(
        send_invite,
        to_email=email,
        display_name=req.display_name,
        tenant_name=tenant.name,
        role=u.role,
        invited_by=me.display_name or me.email,
    )

    return _user_to_item(u, tenant.name)


@router.patch("/users/{user_id}", response_model=UserItem)
def update_user(
    user_id: str,
    req: UpdateUserRequest,
    request: Request,
    me: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> UserItem:
    try:
        uid = UUID(user_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Invalid user_id") from e
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404, "User not found")

    if req.role is not None:
        if req.role not in VALID_ROLES:
            raise HTTPException(400, f"Invalid role. Allowed: {sorted(VALID_ROLES)}")
        target.role = req.role
    if req.display_name is not None:
        target.display_name = req.display_name
    if req.tenant_id is not None:
        try:
            new_tid = UUID(req.tenant_id)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, "Invalid tenant_id") from e
        if db.get(Tenant, new_tid) is None:
            raise HTTPException(404, "Tenant not found")
        target.tenant_id = new_tid
    if req.is_super_admin is not None:
        # Guard: don't let the acting super-admin demote themselves — they'd
        # instantly lose access to this very endpoint.
        if str(target.id) == str(me.id) and req.is_super_admin is False:
            raise HTTPException(400, "You cannot revoke your own super-admin")
        target.is_super_admin = req.is_super_admin

    db.commit()
    db.refresh(target)
    tenant = db.get(Tenant, target.tenant_id)
    log.info("admin.user_updated", user_id=str(target.id))
    return _user_to_item(target, tenant.name if tenant else None)


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
    _: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> list[DebugQueueItem]:
    """Queries the end-user flagged as broken ("the corpus knows this, the
    system didn't find it"). Cross-tenant by default; filter with tenant_id."""
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

    # Batch-load source chunks + docs to avoid N+1.
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
    _: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Remove a query from the debug queue after the super-admin diagnosed it.
    Clears failure_mode + sets reviewer_action=rejected."""
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
    me: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        uid = UUID(user_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Invalid user_id") from e
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404, "User not found")
    if str(target.id) == str(me.id):
        raise HTTPException(400, "You cannot delete your own account")
    db.delete(target)
    db.commit()
    log.info("admin.user_deleted", user_id=user_id)
    return {"status": "ok"}
