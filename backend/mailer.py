"""SendGrid SMTP email — sends ticket notifications."""
import os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.sendgrid.net")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "apikey")
SUPPORT_TO   = [s.strip() for s in os.environ.get("SUPPORT_TO", "support@liquidtech.co.tz").split(",") if s.strip()]
SUPPORT_CC   = [s.strip() for s in os.environ.get("SUPPORT_CC", "").split(",") if s.strip()]
SUPPORT_FROM = os.environ.get("SUPPORT_FROM", "msaada-bot@liquidtech.co.tz")
SUPPORT_FROM_NAME = os.environ.get("SUPPORT_FROM_NAME", "Msaada")

def _build_plain(t):
    lines = [
        f"Ticket reference: {t.get('id')}",
        f"Severity:         {(t.get('severity') or 'medium').upper()}",
        f"Logged at:        {datetime.fromtimestamp(t.get('createdAt') or 0).isoformat()}",
        "", "CUSTOMER",
        f"  Name:      {t.get('customerName') or '(not provided)'}",
    ]
    for k in ("cid", "interface", "contact"):
        if t.get(k): lines.append(f"  {k.title():10}: {t.get(k)}")
    lines += ["", "SUMMARY", t.get("summary") or "(no summary)", "", "---",
              "Logged automatically by Msaada — Liquid Technologies."]
    return "\n".join(lines)

def send_ticket_email(ticket):
    api_key = os.environ.get("SENDGRID_API_KEY") or os.environ.get("SMTP_PASSWORD")
    if not api_key or not SUPPORT_TO:
        return {"sent": False, "reason": "not configured"}
    subject = f"[Msaada] {ticket.get('customerName','')} — {(ticket.get('severity') or 'medium').upper()}"
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{SUPPORT_FROM_NAME} <{SUPPORT_FROM}>"
    msg["To"] = ", ".join(SUPPORT_TO)
    if SUPPORT_CC: msg["Cc"] = ", ".join(SUPPORT_CC)
    msg["Subject"] = subject
    msg.attach(MIMEText(_build_plain(ticket), "plain"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.starttls(); s.login(SMTP_USER, api_key)
            s.sendmail(SUPPORT_FROM, SUPPORT_TO + SUPPORT_CC, msg.as_string())
        return {"sent": True}
    except Exception as e:
        return {"sent": False, "reason": str(e)}
