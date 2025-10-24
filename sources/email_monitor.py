"""Email monitor for semantika.

Monitors an email inbox (IMAP) for new messages and processes:
- Email body text
- Text attachments
- Audio attachments
"""

import imaplib
import email
from email.header import decode_header
from typing import List, Dict, Optional
import asyncio
import tempfile
import os

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from .audio_transcriber import AudioTranscriber

logger = get_logger("email_monitor")


class EmailMonitor:
    """Monitor email inbox for new messages and ingest content."""

    # Supported attachment extensions
    TEXT_EXTENSIONS = {".txt", ".md", ".pdf", ".doc", ".docx"}
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

    def __init__(
        self,
        imap_server: str,
        imap_port: int,
        email_address: str,
        password: str,
        check_interval: int = 60,
        mailbox: str = "INBOX"
    ):
        """
        Initialize email monitor.

        Args:
            imap_server: IMAP server address
            imap_port: IMAP server port (usually 993 for SSL)
            email_address: Email address to monitor
            password: Email password or app password
            check_interval: Check interval in seconds
            mailbox: Mailbox to monitor (default: INBOX)
        """
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.email_address = email_address
        self.password = password
        self.check_interval = check_interval
        self.mailbox = mailbox

        # Initialize audio transcriber
        self.transcriber = AudioTranscriber(model_name="base")

        logger.info(
            "email_monitor_initialized",
            server=imap_server,
            email=email_address,
            check_interval=check_interval
        )

    def _connect(self) -> imaplib.IMAP4_SSL:
        """
        Connect to IMAP server.

        Returns:
            IMAP connection
        """
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_address, self.password)
            mail.select(self.mailbox)

            logger.debug("imap_connected", server=self.imap_server)
            return mail

        except Exception as e:
            logger.error("imap_connection_failed", error=str(e))
            raise

    def _get_client_from_subject(self, subject: str) -> Optional[str]:
        """
        Extract client_id from email subject.

        Expected format: [{client_id}] ...
        Example: [28d8c40a-c661-4b74-b4ea-7ed075339e9d] Monthly Report

        Args:
            subject: Email subject

        Returns:
            Client ID or None
        """
        try:
            if subject.startswith("[") and "]" in subject:
                potential_id = subject[1:subject.index("]")]
                # Basic UUID format check
                if len(potential_id) == 36 and potential_id.count("-") == 4:
                    return potential_id
        except Exception as e:
            logger.debug("client_extraction_failed", subject=subject, error=str(e))

        return None

    def _decode_subject(self, subject: str) -> str:
        """
        Decode email subject.

        Args:
            subject: Encoded subject

        Returns:
            Decoded subject string
        """
        try:
            decoded = decode_header(subject)
            parts = []
            for content, encoding in decoded:
                if isinstance(content, bytes):
                    parts.append(content.decode(encoding or "utf-8"))
                else:
                    parts.append(content)
            return "".join(parts)
        except Exception:
            return subject

    async def _process_email_body(
        self,
        body: str,
        subject: str,
        client_id: str
    ):
        """
        Process email body text.

        Args:
            body: Email body
            subject: Email subject
            client_id: Client UUID
        """
        from core_ingest import IngestPipeline

        try:
            if not body.strip():
                return

            logger.info("processing_email_body", subject=subject)

            pipeline = IngestPipeline(client_id=client_id)

            result = await pipeline.ingest_text(
                text=body,
                title=f"Email: {subject}",
                metadata={
                    "source": "email",
                    "subject": subject
                },
                skip_guardrails=False
            )

            logger.info(
                "email_body_processed",
                subject=subject,
                documents_added=result["documents_added"]
            )

        except Exception as e:
            logger.error("email_body_processing_error", subject=subject, error=str(e))

    async def _process_text_attachment(
        self,
        filename: str,
        content: bytes,
        subject: str,
        client_id: str
    ):
        """
        Process text attachment.

        Args:
            filename: Attachment filename
            content: Attachment bytes
            subject: Email subject
            client_id: Client UUID
        """
        from core_ingest import IngestPipeline

        try:
            logger.info("processing_text_attachment", filename=filename)

            # Decode text
            text = content.decode("utf-8", errors="ignore")

            pipeline = IngestPipeline(client_id=client_id)

            result = await pipeline.ingest_text(
                text=text,
                title=f"Attachment: {filename}",
                metadata={
                    "source": "email_attachment",
                    "filename": filename,
                    "email_subject": subject
                },
                skip_guardrails=False
            )

            logger.info(
                "text_attachment_processed",
                filename=filename,
                documents_added=result["documents_added"]
            )

        except Exception as e:
            logger.error("text_attachment_processing_error", filename=filename, error=str(e))

    async def _process_audio_attachment(
        self,
        filename: str,
        content: bytes,
        subject: str,
        client_id: str
    ):
        """
        Process audio attachment.

        Args:
            filename: Attachment filename
            content: Attachment bytes
            subject: Email subject
            client_id: Client UUID
        """
        try:
            logger.info("processing_audio_attachment", filename=filename)

            result = await self.transcriber.transcribe_and_ingest(
                file_path=content,  # Will use transcribe_bytes internally
                client_id=client_id,
                title=f"Audio: {filename}",
                language=None,
                skip_guardrails=False
            )

            logger.info(
                "audio_attachment_processed",
                filename=filename,
                documents_added=result["documents_added"]
            )

        except Exception as e:
            logger.error("audio_attachment_processing_error", filename=filename, error=str(e))

    async def _process_email(self, mail: imaplib.IMAP4_SSL, email_id: bytes):
        """
        Process a single email.

        Args:
            mail: IMAP connection
            email_id: Email ID
        """
        try:
            # Fetch email
            _, msg_data = mail.fetch(email_id, "(RFC822)")
            email_body = msg_data[0][1]
            message = email.message_from_bytes(email_body)

            # Get subject
            subject = self._decode_subject(message.get("Subject", "No Subject"))

            logger.info("processing_email", subject=subject)

            # Extract client_id
            client_id = self._get_client_from_subject(subject)

            if not client_id:
                logger.warn(
                    "invalid_subject_format",
                    subject=subject,
                    expected_format="[{client_id}] ..."
                )
                # Mark as read and skip
                mail.store(email_id, "+FLAGS", "\\Seen")
                return

            # Verify client exists
            supabase = get_supabase_client()
            client = await supabase.get_client_by_id(client_id)

            if not client:
                logger.warn("client_not_found", client_id=client_id, subject=subject)
                mail.store(email_id, "+FLAGS", "\\Seen")
                return

            # Process email body
            body = ""
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = message.get_payload(decode=True).decode("utf-8", errors="ignore")

            if body.strip():
                await self._process_email_body(body, subject, client_id)

            # Process attachments
            if message.is_multipart():
                for part in message.walk():
                    # Skip non-attachments
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None:
                        continue

                    filename = part.get_filename()
                    if not filename:
                        continue

                    # Get file extension
                    extension = os.path.splitext(filename)[1].lower()
                    content = part.get_payload(decode=True)

                    if extension in self.TEXT_EXTENSIONS:
                        await self._process_text_attachment(
                            filename, content, subject, client_id
                        )
                    elif extension in self.AUDIO_EXTENSIONS:
                        await self._process_audio_attachment(
                            filename, content, subject, client_id
                        )
                    else:
                        logger.debug("unsupported_attachment", filename=filename)

            # Mark as read
            mail.store(email_id, "+FLAGS", "\\Seen")

            logger.info("email_processed", subject=subject)

        except Exception as e:
            logger.error("email_processing_error", error=str(e))

    async def check_inbox(self):
        """Check inbox for new unread emails."""
        try:
            mail = self._connect()

            # Search for unread emails
            _, search_data = mail.search(None, "UNSEEN")
            email_ids = search_data[0].split()

            logger.info("inbox_checked", unread_count=len(email_ids))

            # Process each email
            for email_id in email_ids:
                await self._process_email(mail, email_id)

            # Logout
            mail.logout()

        except Exception as e:
            logger.error("inbox_check_error", error=str(e))

    async def start(self):
        """Start monitoring email inbox."""
        logger.info("email_monitor_started", email=self.email_address)

        while True:
            try:
                await self.check_inbox()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error("monitor_loop_error", error=str(e))
                await asyncio.sleep(self.check_interval)
