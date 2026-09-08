"""Email notifications for customer-visible ticket activity."""

import asyncio
import smtplib
from email.message import EmailMessage

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class EmailNotificationService:
    """Deliver staff replies by email when SMTP is configured."""

    async def send_staff_reply(self, recipient: str, ticket_id: str, reply: str) -> bool:
        if not settings.smtp_host:
            logger.warning(
                "Email notification not sent because SMTP is not configured",
                ticket_id=ticket_id,
                recipient=recipient,
            )
            return False

        message = EmailMessage()
        message["Subject"] = f"Update on your Shiva Support ticket {ticket_id}"
        message["From"] = settings.smtp_from_email
        message["To"] = recipient
        message.set_content(
            f"Our support team replied to ticket {ticket_id}:\n\n{reply}\n\n"
            "You can also view and reply to this message in your support chat."
        )

        try:
            await asyncio.to_thread(self._send, message)
            logger.info("Customer reply notification sent", ticket_id=ticket_id, recipient=recipient)
            return True
        except Exception as exc:
            # The chat reply remains delivered even if an external mail server fails.
            logger.error("Customer reply email failed", ticket_id=ticket_id, error=str(exc))
            return False

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            server.send_message(message)
