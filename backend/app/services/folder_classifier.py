"""Second-pass folder classifier — bounded pick from tenant taxonomy.

Why this exists (see migration 0016 rationale):
The previous single-call classifier let the LLM invent folder names as
free text, biased toward generic-sounding names ("מבנה ארגוני") that
ate a majority of documents via a Matthew effect. Splitting the
folder decision out and constraining it to a curated per-tenant list
kills the generic-catch-all failure mode.

Contract:

    pick_folder(db, tenant_id, title, summary, doc_type)
        → (folder_name: str) if the LLM picked from the active taxonomy
        → None if the LLM said "no_fit" (a FolderSuggestion row is
          created as a side effect for reviewer triage; caller sets
          doc.folder = None).

Idempotent-ish: the same doc classified twice produces two
FolderSuggestion rows on repeated no_fit, which is intended — reviewers
see how often the same shape of doc came up.
"""
from __future__ import annotations

import json
from functools import lru_cache
from uuid import UUID

import structlog

from app.config import settings
from app.models import FolderSuggestion, FolderTaxonomy

log = structlog.get_logger()


@lru_cache(maxsize=1)
def _claude_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


_PICKER_TOOL = {
    "name": "pick_folder",
    "description": (
        "Given a document's title, summary, and doc_type, pick the most "
        "fitting folder from the tenant's active folder set. If nothing "
        "fits, return no_fit=true and suggest a new folder name."
    ),
    "input_schema": {
        "type": "object",
        "required": ["no_fit"],
        "properties": {
            "no_fit": {
                "type": "boolean",
                "description": (
                    "true when NO folder in the provided list is a good "
                    "semantic fit. Do NOT set to false and pick a generic "
                    "folder just because it 'kind of' fits — prefer no_fit "
                    "and let a reviewer add a proper new folder."
                ),
            },
            "folder_name": {
                "type": "string",
                "description": (
                    "The exact name of the picked folder (must be one of "
                    "the provided names). Only set when no_fit=false."
                ),
            },
            "proposed_name": {
                "type": "string",
                "description": (
                    "When no_fit=true, propose a short (1-2 word) Hebrew "
                    "folder name that would fit this document."
                ),
            },
            "proposed_description": {
                "type": "string",
                "description": (
                    "When no_fit=true, one-sentence description of what "
                    "kinds of documents belong in this new folder."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "One short Hebrew sentence explaining the choice.",
            },
        },
    },
}


def _system_prompt(taxonomy: list[FolderTaxonomy]) -> str:
    lines = [
        "אתה מסווג מסמכים לתיקיות. תפקידך: לבחור תיקייה אחת מרשימת התיקיות הפעילות של הארגון — או להצהיר שאין התאמה טובה ולהציע תיקייה חדשה.",
        "",
        "כלל ברזל: אל תבחר תיקייה 'סתם כי היא נשמעת גנרית מספיק'. אם המסמך לא באמת שייך לאחת מהתיקיות הקיימות — החזר no_fit=true. עדיף לחכות לסוקר שיוסיף תיקייה נכונה מאשר להעמיס עוד מסמך על תיקיית ברירת-מחדל.",
        "",
        "תיקיות פעילות של הארגון:",
    ]
    if not taxonomy:
        lines.append("(אין תיקיות פעילות. חובה להחזיר no_fit=true עם הצעה.)")
    for f in taxonomy:
        desc = (f.description or "").strip()
        if desc:
            lines.append(f"- {f.name}: {desc}")
        else:
            lines.append(f"- {f.name}")
    return "\n".join(lines)


def _load_active_taxonomy(db, tenant_id: UUID) -> list[FolderTaxonomy]:
    return (
        db.query(FolderTaxonomy)
        .filter(FolderTaxonomy.tenant_id == tenant_id)
        .filter(FolderTaxonomy.active.is_(True))
        .order_by(FolderTaxonomy.name)
        .all()
    )


def _record_suggestion(
    db,
    *,
    tenant_id: UUID,
    proposed_name: str,
    proposed_description: str,
    source_doc_id: UUID | None,
    source_title: str,
    source_summary: str,
) -> None:
    """Insert a pending FolderSuggestion. Deduped weakly: if the same
    proposed_name is already pending for this tenant, we don't insert a
    duplicate — the count of source docs per pending name is implicit in
    the reviewer view via multiple source_doc_ids over time."""
    existing = (
        db.query(FolderSuggestion)
        .filter(FolderSuggestion.tenant_id == tenant_id)
        .filter(FolderSuggestion.status == "pending")
        .filter(FolderSuggestion.proposed_name == proposed_name)
        .first()
    )
    if existing is not None:
        return
    db.add(
        FolderSuggestion(
            tenant_id=tenant_id,
            proposed_name=proposed_name,
            proposed_description=proposed_description or None,
            source_doc_id=source_doc_id,
            source_title=source_title or None,
            source_summary=source_summary or None,
        )
    )


def pick_folder(
    db,
    *,
    tenant_id: UUID,
    title: str,
    summary: str,
    doc_type: str,
    source_doc_id: UUID | None = None,
) -> str | None:
    """Second-pass folder pick. Returns folder name or None (with a
    FolderSuggestion side effect)."""
    taxonomy = _load_active_taxonomy(db, tenant_id)
    valid_names = {f.name for f in taxonomy}

    client = _claude_client()
    user_content = (
        f"כותרת: {title}\n"
        f"סוג מסמך: {doc_type or '(לא ידוע)'}\n"
        f"תקציר: {summary or '(לא ניתן)'}\n\n"
        "בחר תיקייה מהרשימה או החזר no_fit=true."
    )
    try:
        resp = client.messages.create(
            model=settings.claude_extract_model,
            max_tokens=400,
            system=_system_prompt(taxonomy),
            tools=[_PICKER_TOOL],
            tool_choice={"type": "tool", "name": "pick_folder"},
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("folder_classifier.claude_failed", err=str(e))
        return None

    for block in resp.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        inp = getattr(block, "input", None)
        if not isinstance(inp, dict):
            continue
        if inp.get("no_fit"):
            proposed = (inp.get("proposed_name") or "").strip()
            if proposed:
                _record_suggestion(
                    db,
                    tenant_id=tenant_id,
                    proposed_name=proposed,
                    proposed_description=(inp.get("proposed_description") or "").strip(),
                    source_doc_id=source_doc_id,
                    source_title=title,
                    source_summary=summary,
                )
            log.info(
                "folder_classifier.no_fit",
                proposed=proposed,
                title=title,
            )
            return None
        picked = (inp.get("folder_name") or "").strip()
        if picked and picked in valid_names:
            return picked
        # Guardrail: model returned a name not in the list (rare — happens
        # when it fabricates variants). Treat as no_fit so we don't
        # silently write bad folder names.
        log.warning(
            "folder_classifier.invalid_pick",
            picked=picked,
            valid=list(valid_names),
        )
        if picked:
            _record_suggestion(
                db,
                tenant_id=tenant_id,
                proposed_name=picked,
                proposed_description="",
                source_doc_id=source_doc_id,
                source_title=title,
                source_summary=summary,
            )
        return None
    return None
