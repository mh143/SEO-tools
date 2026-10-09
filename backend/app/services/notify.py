"""Optional email alerts. Without SMTP settings, alerts are in-app notifications only."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ROLE_RANK, Membership, Role, User

log = logging.getLogger(__name__)


def send_alert_email(db: Session, org_id, run, regressions, new_count: int) -> bool:
    s = get_settings()
    if not s.smtp_host or not s.smtp_from:
        return False
    recipients = [u.email for m, u in db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.org_id == org_id))
        if ROLE_RANK[m.role] >= ROLE_RANK[Role.admin]]
    if not recipients:
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[{s.app_name}] Audit alert: {len(regressions)} regression(s), {new_count} new issue(s)"
    msg["From"] = s.smtp_from
    msg["To"] = ", ".join(recipients)
    lines = [f"- {f.title}: {f.url or 'site-wide'}" for f in regressions[:20]]
    msg.set_content(
        f"A scheduled audit of {run.start_url} finished.\n\nRegressions:\n" + ("\n".join(lines) or "none")
        + f"\n\nNew issues: {new_count}\n\nView: {s.public_app_url}/app/{org_id}/crawls/{run.id}\n"
    )
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception:
        log.exception("alert email failed")
        return False
