"""Email confirmation sender for Parking Helper reservations."""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass


GMAIL_USER = os.environ.get("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()


def looks_like_email(value: str) -> bool:
    value = (value or "").strip()
    return "@" in value and "." in value.split("@")[-1]


def send_reservation_confirmation(
    to_email: str,
    reserved_by: str,
    lot_id: str,
    spot_id: str,
    duration_minutes: int,
    expires_at: str,
    reservation_id: int | str = "",
) -> tuple[bool, str]:
    """Send a reservation confirmation email and return (success, message)."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return False, "GMAIL_USER or GMAIL_APP_PASSWORD not set in the environment."

    if not looks_like_email(to_email):
        return False, f"'{to_email}' does not look like a valid email address."

    subject = f"Parking Confirmation - {lot_id} / {spot_id}"
    html_body = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:520px;margin:0 auto;
                background:#11131A;color:#F0F0F5;border-radius:14px;padding:32px;">
      <div style="font-size:22px;font-weight:700;color:#FF3B3B;margin-bottom:4px;">Parking Helper</div>
      <div style="font-size:13px;color:#8B8FA3;margin-bottom:24px;">Reservation Confirmed</div>
      <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:12px;padding:20px;margin-bottom:20px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tr><td style="color:#8B8FA3;padding:6px 0;">Reservation ID</td><td style="color:#F0F0F5;text-align:right;font-weight:600;">#{reservation_id}</td></tr>
          <tr><td style="color:#8B8FA3;padding:6px 0;">Account</td><td style="color:#F0F0F5;text-align:right;">{reserved_by}</td></tr>
          <tr><td style="color:#8B8FA3;padding:6px 0;">Parking Lot</td><td style="color:#F0F0F5;text-align:right;font-weight:600;">{lot_id}</td></tr>
          <tr><td style="color:#8B8FA3;padding:6px 0;">Spot</td><td style="color:#B7EE85;text-align:right;font-weight:700;font-size:16px;">{spot_id}</td></tr>
          <tr><td style="color:#8B8FA3;padding:6px 0;">Duration</td><td style="color:#F0F0F5;text-align:right;">{duration_minutes} minutes</td></tr>
          <tr><td style="color:#8B8FA3;padding:6px 0;">Expires at</td><td style="color:#FFB300;text-align:right;">{expires_at}</td></tr>
        </table>
      </div>
      <div style="background:#B7EE8511;border:1px solid #B7EE8533;border-radius:10px;padding:14px;font-size:13px;color:#B7EE85;margin-bottom:24px;">
        Please proceed to <strong>{lot_id}</strong> and park in spot <strong>{spot_id}</strong> before your reservation expires.
      </div>
      <div style="font-size:11px;color:#666;text-align:center;">Parking Helper</div>
    </div>
    """

    plain_body = (
        f"Parking Reservation Confirmed\n\n"
        f"ID: #{reservation_id}\n"
        f"Account: {reserved_by}\n"
        f"Lot: {lot_id}\n"
        f"Spot: {spot_id}\n"
        f"Duration: {duration_minutes} minutes\n"
        f"Expires: {expires_at}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Parking Helper <{GMAIL_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())
        return True, f"Confirmation sent to {to_email}"
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail authentication failed. Check GMAIL_USER and GMAIL_APP_PASSWORD."
    except Exception as exc:
        return False, str(exc)
