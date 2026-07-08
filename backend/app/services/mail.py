"""Transactional email via Resend.

Two callers today:
  - Admin panel → create user → welcome / invite email
  - Search → mark-broken → alert to all super-admins

The public entry points are ``send_invite`` and ``send_broken_answer_alert``.
Both are safe to call from a FastAPI BackgroundTask — they never raise, so
a mail outage never breaks the user's request.

If ``RESEND_API_KEY`` is empty (local dev without keys), we log the payload
and return without hitting the network.
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
    .card { max-width: 560px; margin: 0 auto; background: #fafaf9; border: 1px solid #e7e5e4; padding: 40px 32px; }
    h1 { font-size: 28px; font-weight: 900; margin: 0 0 12px; letter-spacing: -0.01em; }
    h2 { font-size: 18px; font-weight: 700; margin: 24px 0 6px; letter-spacing: -0.005em; }
    p  { line-height: 1.65; margin: 0 0 12px; font-size: 15px; }
    .tag { display: inline-block; text-transform: uppercase; letter-spacing: 0.25em; font-size: 10px; font-weight: 700; color: #b8412b; margin-bottom: 12px; }
    blockquote { margin: 12px 0; padding: 10px 14px; border-right: 3px solid #b8412b; background: #f2f0ee; font-size: 14px; }
    .foot { margin-top: 32px; padding-top: 20px; border-top: 1px solid #e7e5e4; font-size: 12px; color: #525252; }
  </style>
"""


def _wrap_html(body: str) -> str:
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>{_BASE_STYLE}</head>
<body>
  <div style="padding: 32px 16px;">
    <div class="card">
      {body}
      <div class="foot">
        Klaser · <a href="{html.escape(settings.klaser_app_url)}">klaser.co.il</a>
      </div>
    </div>
  </div>
</body>
</html>"""


# ─── Invite / welcome ───────────────────────────────────────────────────


def send_invite(
    *,
    to_email: str,
    display_name: str | None,
    tenant_name: str,
    role: str,
    invited_by: str | None,
) -> None:
    """Sent when the super-admin adds a new user to a tenant."""
    role_labels = {"admin": "מנהל", "reviewer": "בודק", "secretary": "מזכיר/ה"}
    role_he = role_labels.get(role, role)
    login_url = settings.klaser_app_url

    greeting_name = (display_name or "").strip() or to_email.split("@")[0]

    html_body = _wrap_html(
        f"""
        <div class="tag">ברוכים הבאים ל-Klaser</div>
        <h1>שלום {html.escape(greeting_name)}</h1>
        <p>הוספת חשבון בארגון <strong>{html.escape(tenant_name)}</strong> ב-Klaser
        {"על ידי " + html.escape(invited_by) if invited_by else ""}.</p>
        <p>התפקיד שלך במערכת: <strong>{role_he}</strong>.</p>
        <p>Klaser הוא כלי לזיכרון ארגוני — שאלה בעברית, תשובה מבוססת מקור מתוך
        המסמכים המחייבים של הארגון (תקנון, פרוטוקולים, החלטות).</p>

        <p style="margin: 32px 0;">
          <a href="{html.escape(login_url)}" class="btn">כניסה למערכת ←</a>
        </p>

        <p class="muted">
          הכניסה מתבצעת עם חשבון Google של הכתובת <strong>{html.escape(to_email)}</strong>.
          אם עוד אין לך חשבון Google בכתובת הזו — פתח אחד או פנה למי שהזמין אותך.
        </p>
        """
    )

    text_body = (
        f"שלום {greeting_name},\n\n"
        f"נוספת לארגון {tenant_name} ב-Klaser"
        + (f" על ידי {invited_by}" if invited_by else "")
        + f".\nהתפקיד שלך: {role_he}.\n\n"
        f"כניסה למערכת: {login_url}\n\n"
        f"הכניסה מתבצעת עם חשבון Google של הכתובת {to_email}.\n\n"
        f"— Klaser"
    )

    _send(
        Message(
            to=to_email,
            subject=f"ברוכים הבאים ל-Klaser · {tenant_name}",
            html_body=html_body,
            text_body=text_body,
        )
    )


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
