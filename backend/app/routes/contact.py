"""Public landing-page contact form.

Unauthenticated POST — anyone with the marketing site URL can submit.
Sends a Resend email to tal.gurevich@elrom.tv. No storage; the mail *is*
the record. Basic length caps guard against runaway payloads; if spam
becomes a real problem we'll add a CAPTCHA or honeypot in a follow-up.
"""
from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.services.mail import send_contact_message

log = structlog.get_logger()

router = APIRouter()

# Lightweight validation — the address is going straight to a human, not
# a mailer that needs RFC-perfect input. Requires an @ and a dot in the
# domain half, and no whitespace. Keeps us off the email-validator dep.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_RE = re.compile(r"^[\d\s\-\+\(\)]{6,20}$")


class ContactPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    message: str = Field(min_length=1, max_length=4000)


@router.post("/contact")
def submit_contact(
    payload: ContactPayload,
    background: BackgroundTasks,
) -> dict:
    email = payload.email.strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="כתובת אימייל לא תקינה")
    if payload.phone and not _PHONE_RE.match(payload.phone.strip()):
        raise HTTPException(status_code=422, detail="מספר טלפון לא תקין")

    background.add_task(
        send_contact_message,
        name=payload.name,
        email=email,
        phone=payload.phone,
        message=payload.message,
    )
    log.info("contact.submitted", email=email, name=payload.name)
    return {"status": "ok"}
