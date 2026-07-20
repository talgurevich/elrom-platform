"""Transactional email via Resend.

Callers today (all Takanon-side domain email):
  - Search → mark-broken → alert to all super-admins.
  - Landing page contact form → send_contact_message.
  - Weekly cron → lexicon digest to every super-admin.

Auth email (invite, welcome, password reset) moved to the identity
service on 2026-07-14 — those helpers now live in
`klaser-identity/app/services/mail.py`, not here.

Public entry points: ``send_broken_answer_alert``,
``send_contact_message``, ``send_lexicon_digest``. All are safe to call
from a FastAPI BackgroundTask (or a cron) — they never raise, so a
mail outage never breaks the caller.

If ``RESEND_API_KEY`` is empty (local dev without keys), we log the
payload and return without hitting the network.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Iterable

import resend
import structlog

from app.config import settings

log = structlog.get_logger()


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    html_body: str
    text_body: str


def _from_line() -> str:
    """Resend accepts "Name <addr>" — use the app's display name."""
    name = (settings.mail_from_name or "Klaser").strip()
    email = settings.mail_from_email
    return f"{name} <{email}>" if name else email


def _send(msg: Message) -> None:
    """Fire-and-forget send. Never raises."""
    if not settings.resend_api_key:
        log.info(
            "mail.dry_run",
            to=msg.to,
            subject=msg.subject,
            reason="RESEND_API_KEY not set",
        )
        return
    resend.api_key = settings.resend_api_key
    try:
        resend.Emails.send(
            {
                "from": _from_line(),
                "to": [msg.to],
                "subject": msg.subject,
                "html": msg.html_body,
                "text": msg.text_body,
            }
        )
        log.info("mail.sent", to=msg.to, subject=msg.subject)
    except Exception as e:  # noqa: BLE001 — must not propagate
        log.warning("mail.send_failed", to=msg.to, error=str(e))


# ─────────────────────────────────────────────────────────────────────────
# Templates — RTL Hebrew, simple table-based layout so it renders in every
# mail client without a build step. Kept dependency-free on purpose.
# ─────────────────────────────────────────────────────────────────────────


_BASE_STYLE = """
  <meta charset="utf-8">
  <style>
    body { margin: 0; padding: 0; background: #fafaf9; font-family: 'Heebo', 'Assistant', system-ui, sans-serif; color: #171717; direction: rtl; }
    a { color: #b8412b; text-decoration: none; }
    .btn { display: inline-block; background: #171717; color: #fafaf9 !important; text-decoration: none;
           padding: 14px 28px; font-weight: 700; letter-spacing: 0.02em; }
    .muted { color: #525252; font-size: 13px; line-height: 1.6; }
    .card { max-width: 560px; margin: 0 auto; background: #fafaf9; border: 1px solid #e7e5e4; padding: 40px 32px; direction: rtl; text-align: right; }
    h1 { font-size: 28px; font-weight: 900; margin: 0 0 12px; letter-spacing: -0.01em; }
    h2 { font-size: 18px; font-weight: 700; margin: 24px 0 6px; letter-spacing: -0.005em; }
    p  { line-height: 1.65; margin: 0 0 12px; font-size: 15px; }
    .tag { display: inline-block; text-transform: uppercase; letter-spacing: 0.25em; font-size: 10px; font-weight: 700; color: #b8412b; margin-bottom: 12px; }
    blockquote { margin: 12px 0; padding: 10px 14px; border-right: 3px solid #b8412b; background: #f2f0ee; font-size: 14px; }
    .foot { margin-top: 32px; padding-top: 20px; border-top: 1px solid #e7e5e4; font-size: 12px; color: #525252; }
  </style>
"""


# Gmail and Outlook strip <html>/<body> and their CSS, so `dir="rtl"` on those
# is lost. We repeat dir="rtl" and inline direction/text-align on every wrapper
# div so RTL survives the strip in every client. Any template using
# _wrap_html inherits RTL by default — do not add new wrappers without these.
def _wrap_html(body: str) -> str:
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>{_BASE_STYLE}</head>
<body dir="rtl" style="direction: rtl; text-align: right;">
  <div dir="rtl" style="padding: 32px 16px; direction: rtl; text-align: right;">
    <div class="card" dir="rtl" style="direction: rtl; text-align: right;">
      {body}
      <div class="foot" dir="rtl" style="direction: rtl; text-align: right;">
        Klaser · <a href="{html.escape(settings.klaser_app_url)}">klaser.co.il</a>
      </div>
    </div>
  </div>
</body>
</html>"""


# ─── Broken-answer alert ────────────────────────────────────────────────


def send_broken_answer_alert(
    *,
    to_emails: Iterable[str],
    tenant_name: str,
    question: str,
    answer: str | None,
    query_id: str,
    marked_by_email: str | None,
) -> None:
    """Sent to every super-admin when a user marks an answer broken."""
    debug_url = f"{settings.klaser_app_url.rstrip('/')}/#admin"
    # Trim long text so a runaway answer doesn't blow up the email.
    short_answer = (answer or "(אין תשובה)").strip()
    if len(short_answer) > 1200:
        short_answer = short_answer[:1200] + "…"

    marked_line = (
        f'<p class="muted">סימן: {html.escape(marked_by_email)}</p>'
        if marked_by_email
        else ""
    )

    html_body = _wrap_html(
        f"""
        <div class="tag">Klaser · תור באגים</div>
        <h1>תשובה סומנה כשגויה</h1>
        <p>משתמש בארגון <strong>{html.escape(tenant_name)}</strong> סימן תשובה
        כשגויה — לפי הסימון, הקורפוס מכיל את התשובה הנכונה והמערכת פשוט לא
        מצאה אותה.</p>
        {marked_line}

        <h2>השאלה</h2>
        <blockquote>{html.escape(question)}</blockquote>

        <h2>התשובה שהוחזרה</h2>
        <blockquote>{html.escape(short_answer)}</blockquote>

        <p style="margin: 28px 0;">
          <a href="{html.escape(debug_url)}" class="btn">פתח בתור הבאגים ←</a>
        </p>

        <p class="muted">מזהה שאילתה: <code>{html.escape(query_id)}</code></p>
        """
    )

    text_body = (
        f"תשובה סומנה כשגויה ({tenant_name}).\n\n"
        f"שאלה:\n{question}\n\n"
        f"תשובה שהוחזרה:\n{short_answer}\n\n"
        f"פתח בתור הבאגים: {debug_url}\n"
        f"query_id: {query_id}\n"
    )

    for addr in to_emails:
        _send(
            Message(
                to=addr,
                subject=f"[Klaser] תשובה שגויה · {tenant_name}",
                html_body=html_body,
                text_body=text_body,
            )
        )


# ─── Public contact form ────────────────────────────────────────────────


def send_contact_message(
    *,
    name: str,
    email: str,
    phone: str | None,
    message: str,
) -> None:
    """Public landing-page contact form → Tal's inbox.

    Recipient is hardcoded rather than a setting: this is a marketing
    surface, not per-tenant. Sender fields are user-supplied and untrusted —
    everything gets html.escape'd before hitting the template.
    """
    recipient = "tal.gurevich@elrom.tv"

    safe_name = html.escape(name.strip())
    safe_email = html.escape(email.strip())
    safe_phone = html.escape((phone or "").strip()) or "—"
    safe_message = html.escape(message.strip()).replace("\n", "<br>")

    html_body = _wrap_html(
        f"""
        <div class="tag">Klaser · פנייה חדשה</div>
        <h1>פנייה חדשה מהאתר</h1>
        <p>התקבלה פנייה חדשה דרך טופס יצירת הקשר.</p>

        <h2>שם</h2>
        <blockquote>{safe_name}</blockquote>

        <h2>אימייל</h2>
        <blockquote><a href="mailto:{safe_email}">{safe_email}</a></blockquote>

        <h2>טלפון</h2>
        <blockquote>{safe_phone}</blockquote>

        <h2>הודעה</h2>
        <blockquote>{safe_message}</blockquote>
        """
    )

    text_body = (
        f"פנייה חדשה מהאתר\n\n"
        f"שם: {name}\n"
        f"אימייל: {email}\n"
        f"טלפון: {phone or '—'}\n\n"
        f"הודעה:\n{message}\n"
    )

    _send(
        Message(
            to=recipient,
            subject=f"[Klaser] פנייה חדשה — {name}",
            html_body=html_body,
            text_body=text_body,
        )
    )


# ─── In-app support request ─────────────────────────────────────────────


@dataclass(frozen=True)
class SupportTurnSnapshot:
    """One turn in the conversation as it should render in the email.
    Detached from SQLAlchemy so the mailer never holds a session."""
    role: str  # "user" | "assistant"
    text: str


def send_support_request(
    *,
    tenant_name: str,
    user_email: str,
    user_display_name: str | None,
    note: str,
    question: str,
    conversation_id: str,
    conversation_deep_link: str,
    query_id: str,
    turns: list[SupportTurnSnapshot],
) -> None:
    """User-initiated "report an issue" from the search UI → Tal's inbox.

    Recipient is hardcoded — this is the platform's own support channel,
    not tenant-configurable. Everything user-supplied is escaped before
    templating.
    """
    recipient = "tal.gurevich@elrom.tv"

    safe_tenant = html.escape(tenant_name or "—")
    safe_user = html.escape(user_display_name or user_email)
    safe_email = html.escape(user_email)
    safe_note = html.escape(note.strip()).replace("\n", "<br>") or "—"
    safe_question = html.escape(question).replace("\n", "<br>")
    safe_link = html.escape(conversation_deep_link)

    transcript_html = ""
    for t in turns:
        role_label = "משתמש" if t.role == "user" else "מערכת"
        role_color = "#171717" if t.role == "user" else "#b8412b"
        safe_text = html.escape(t.text or "").replace("\n", "<br>")
        transcript_html += (
            f'<div style="margin: 10px 0; padding: 10px 14px; '
            f'border-right: 3px solid {role_color}; background: #f2f0ee;">'
            f'<div style="font-size:11px; letter-spacing:0.2em; text-transform:uppercase; '
            f'color:{role_color}; font-weight:700; margin-bottom:6px;">{role_label}</div>'
            f'<div style="font-size:14px; line-height:1.6;">{safe_text}</div>'
            f"</div>"
        )

    html_body = _wrap_html(
        f"""
        <div class="tag">Klaser · דיווח מהמערכת</div>
        <h1>דיווח בעיה משיחה</h1>
        <p>משתמש דיווח על בעיה בשיחה. הפרטים למטה — פתח את השיחה בעזרת הקישור בסוף.</p>

        <h2>ארגון</h2>
        <blockquote>{safe_tenant}</blockquote>

        <h2>משתמש</h2>
        <blockquote>{safe_user} · <a href="mailto:{safe_email}">{safe_email}</a></blockquote>

        <h2>הערת המשתמש</h2>
        <blockquote>{safe_note}</blockquote>

        <h2>השאלה שהופנתה לתשובה שדווחה</h2>
        <blockquote>{safe_question}</blockquote>

        <h2>מזהי ניפוי</h2>
        <p class="muted">
          conversation_id: <code>{html.escape(conversation_id)}</code><br>
          query_id: <code>{html.escape(query_id)}</code>
        </p>

        <h2>שיחה מלאה</h2>
        {transcript_html or '<p class="muted">אין תורות נוספים.</p>'}

        <p style="margin-top:24px;">
          <a class="btn" href="{safe_link}">פתח את השיחה</a>
        </p>
        """
    )

    text_lines = [
        "דיווח בעיה משיחה",
        "",
        f"ארגון: {tenant_name}",
        f"משתמש: {user_display_name or user_email} <{user_email}>",
        "",
        f"הערת המשתמש: {note.strip() or '—'}",
        "",
        f"שאלה שדווחה: {question}",
        "",
        f"conversation_id: {conversation_id}",
        f"query_id: {query_id}",
        f"link: {conversation_deep_link}",
        "",
        "שיחה מלאה:",
    ]
    for t in turns:
        role_label = "משתמש" if t.role == "user" else "מערכת"
        text_lines.append(f"[{role_label}] {t.text}")
    text_body = "\n".join(text_lines)

    _send(
        Message(
            to=recipient,
            subject=f"[Klaser] דיווח בעיה — {tenant_name}",
            html_body=html_body,
            text_body=text_body,
        )
    )


# ─── Weekly lexicon digest ──────────────────────────────────────────────


@dataclass(frozen=True)
class LexiconEntrySnapshot:
    """Just enough of a Lexicon row to render into the digest — kept as a
    plain dataclass so the digest sender doesn't hold SQLAlchemy sessions."""

    term: str
    expansion: str
    confidence: float | None
    status: str  # active | pending | rejected
    source: str  # manual | learned
    updated_at_iso: str


def _fmt_confidence(c: float | None) -> str:
    if c is None:
        return ""
    return f'<span class="muted" style="margin-right:6px;">ביטחון: {c:.2f}</span>'


def _lexicon_bucket_html(title: str, tag_color: str, entries: list[LexiconEntrySnapshot]) -> str:
    if not entries:
        return ""
    rows = ""
    for e in entries:
        rows += (
            '<li style="margin-bottom:8px;">'
            f'<strong>{html.escape(e.term)}</strong> '
            f'<span class="muted">←</span> {html.escape(e.expansion)}'
            f'{_fmt_confidence(e.confidence)}'
            "</li>"
        )
    return (
        f'<h3 style="margin:20px 0 6px; font-size:15px; color:{tag_color};">'
        f'{title} <span class="muted" style="font-size:12px;">({len(entries)})</span>'
        "</h3>"
        f'<ul style="margin:0; padding-right:20px; list-style-position:outside;">'
        f"{rows}</ul>"
    )


def _tenant_section_html(
    tenant_name: str,
    pending: list[LexiconEntrySnapshot],
    active: list[LexiconEntrySnapshot],
    rejected: list[LexiconEntrySnapshot],
) -> str:
    body = ""
    body += _lexicon_bucket_html("🟡 ממתינים לבדיקה", "#b8412b", pending)
    body += _lexicon_bucket_html("✅ חדשים ומאושרים", "#171717", active)
    body += _lexicon_bucket_html("❌ נדחו", "#525252", rejected)
    return (
        f'<div style="margin-top:28px; padding-top:20px; border-top:1px solid #e7e5e4;">'
        f'<h2 style="margin-bottom:4px;">{html.escape(tenant_name)}</h2>'
        f"{body}</div>"
    )


def _tenant_section_text(
    tenant_name: str,
    pending: list[LexiconEntrySnapshot],
    active: list[LexiconEntrySnapshot],
    rejected: list[LexiconEntrySnapshot],
) -> str:
    lines: list[str] = [f"\n== {tenant_name} =="]
    for title, entries in [
        ("ממתינים לבדיקה", pending),
        ("חדשים ומאושרים", active),
        ("נדחו", rejected),
    ]:
        if not entries:
            continue
        lines.append(f"\n{title} ({len(entries)}):")
        for e in entries:
            conf = f" [ביטחון: {e.confidence:.2f}]" if e.confidence is not None else ""
            lines.append(f"  • {e.term} ← {e.expansion}{conf}")
    return "\n".join(lines)


def send_lexicon_digest(
    *,
    to_email: str,
    admin_display_name: str | None,
    tenant_sections: list[
        tuple[
            str,  # tenant name
            list[LexiconEntrySnapshot],  # pending
            list[LexiconEntrySnapshot],  # active
            list[LexiconEntrySnapshot],  # rejected
        ]
    ],
) -> None:
    """Weekly-digest email — one per super-admin. ``tenant_sections`` only
    contains tenants with activity in the window; the caller is responsible
    for skipping quiet weeks (no email if the list is empty)."""
    if not tenant_sections:
        log.info("mail.digest_skip_empty", to=to_email)
        return

    total_pending = sum(len(p) for _, p, _, _ in tenant_sections)
    total_active = sum(len(a) for _, _, a, _ in tenant_sections)
    total_rejected = sum(len(r) for _, _, _, r in tenant_sections)
    total = total_pending + total_active + total_rejected

    lexicon_url = f"{settings.klaser_app_url.rstrip('/')}/#lexicon"
    greeting_name = (admin_display_name or "").strip() or to_email.split("@")[0]

    tenants_html = "".join(
        _tenant_section_html(name, p, a, r) for name, p, a, r in tenant_sections
    )
    tenants_text = "\n".join(
        _tenant_section_text(name, p, a, r) for name, p, a, r in tenant_sections
    )

    pending_line = (
        f'<p class="muted"><strong>{total_pending}</strong> ממתינים לבדיקה שלך.</p>'
        if total_pending
        else ""
    )

    html_body = _wrap_html(
        f"""
        <div class="tag">Klaser · סיכום שבועי</div>
        <h1>מילון המונחים השבוע</h1>
        <p>שלום {html.escape(greeting_name)},</p>
        <p>בשבוע האחרון היו <strong>{total}</strong> עדכונים במילון על פני
        <strong>{len(tenant_sections)}</strong> ארגונים.</p>
        {pending_line}

        {tenants_html}

        <p style="margin: 32px 0;">
          <a href="{html.escape(lexicon_url)}" class="btn">פתח את המילון ←</a>
        </p>
        """
    )

    text_body = (
        f"סיכום שבועי — מילון מונחים\n"
        f"שלום {greeting_name},\n\n"
        f"בשבוע האחרון היו {total} עדכונים במילון "
        f"על פני {len(tenant_sections)} ארגונים.\n"
        + (f"{total_pending} ממתינים לבדיקה שלך.\n" if total_pending else "")
        + tenants_text
        + f"\n\nפתח את המילון: {lexicon_url}\n"
    )

    _send(
        Message(
            to=to_email,
            subject=f"[Klaser] סיכום שבועי · מילון ({total} עדכונים)",
            html_body=html_body,
            text_body=text_body,
        )
    )
