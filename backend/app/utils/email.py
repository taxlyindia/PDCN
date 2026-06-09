import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> bool:
    """
    Send an email. Uses aiosmtplib when SMTP credentials are configured.
    Falls back to logging in development mode.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.info(f"[DEV EMAIL] To: {to} | Subject: {subject}\n{body}")
        return True

    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        msg.attach(MIMEText(body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        return False


async def send_password_reset_email(email: str, token: str, full_name: str) -> bool:
    reset_link = f"{settings.FRONTEND_URL}/reset-password.html?token={token}"
    subject = "Password Reset Request – CRM Platform"
    body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">
      <h2 style="color: #1a1a2e;">Password Reset</h2>
      <p>Hi {full_name},</p>
      <p>We received a request to reset your password. Click the button below to set a new password:</p>
      <a href="{reset_link}" style="display:inline-block;padding:12px 24px;background:#6c63ff;color:#fff;text-decoration:none;border-radius:6px;margin:16px 0;">
        Reset Password
      </a>
      <p>This link expires in <strong>30 minutes</strong>.</p>
      <p>If you didn't request this, you can safely ignore this email.</p>
      <hr/>
      <small style="color:#888;">CRM Platform – Automated Email</small>
    </body></html>
    """
    return await send_email(email, subject, body)


async def send_trial_expiry_notification(email: str, company: str) -> bool:
    subject = "Your Trial Has Expired – Action Required"
    body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">
      <h2 style="color: #e74c3c;">Trial Expired</h2>
      <p>Hi,</p>
      <p>The 10-day free trial for <strong>{company}</strong> has ended.</p>
      <p>Your account is currently under review. The platform administrator will contact you shortly to approve your subscription.</p>
      <p>If you have questions, please reach out to support.</p>
      <hr/>
      <small style="color:#888;">CRM Platform – Automated Email</small>
    </body></html>
    """
    return await send_email(email, subject, body)
