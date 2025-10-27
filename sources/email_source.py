"""Email source implementation using IMAP.

Fetches emails from IMAP server, aggregates content (body, attachments, transcriptions),
and matches emails to organizations.
"""

import imaplib
import email
from email.header import decode_header
from email.utils import parseaddr
from typing import List, Optional, Dict, Any
import base64
import io

from sources.base_source import BaseSource, SourceContent
from utils.config import settings
from utils.logger import get_logger
from utils.supabase_client import get_supabase_client

logger = get_logger("email_source")


class EmailSource(BaseSource):
    """IMAP email source implementation."""

    def __init__(self):
        """Initialize email source with IMAP configuration."""
        super().__init__()
        self.imap_host = settings.imap_host
        self.imap_port = settings.imap_port
        self.imap_user = settings.imap_user
        self.imap_password = settings.imap_password
        self.inbox_folder = settings.imap_inbox_folder

    async def fetch(self) -> List[SourceContent]:
        """
        Fetch unread emails from IMAP.

        Returns:
            List of SourceContent objects
        """
        logger.info("fetch_emails_start")

        try:
            # Connect to IMAP
            mail = self._connect_imap()

            # Select inbox
            mail.select(self.inbox_folder)

            # Search for unread emails
            status, messages = mail.search(None, 'UNSEEN')

            if status != 'OK':
                logger.warn("imap_search_failed", status=status)
                mail.logout()
                return []

            email_ids = messages[0].split()
            logger.info("unread_emails_found", count=len(email_ids))

            source_contents = []

            for email_id in email_ids:
                try:
                    # Fetch email
                    email_data = self._fetch_email(mail, email_id)

                    if not email_data:
                        continue

                    # Match organization
                    org_slug = await self.match_organization(email_data)

                    if not org_slug:
                        logger.warn(
                            "email_no_org_match",
                            to=email_data.get("to"),
                            subject=email_data.get("subject")
                        )
                        continue

                    # Aggregate content
                    aggregated = await self._aggregate_email_content(email_data)

                    source_content = SourceContent(
                        organization_slug=org_slug,
                        source_type="email",
                        source_id=email_data["message_id"],
                        raw_content=aggregated,
                        metadata={
                            "from": email_data.get("from"),
                            "to": email_data.get("to"),
                            "subject": email_data.get("subject"),
                            "date": email_data.get("date")
                        }
                    )

                    source_contents.append(source_content)
                    logger.info("email_processed", message_id=email_data["message_id"])

                except Exception as e:
                    logger.error("email_processing_error", email_id=email_id.decode(), error=str(e))
                    continue

            mail.logout()
            logger.info("fetch_emails_completed", count=len(source_contents))

            return source_contents

        except Exception as e:
            logger.error("fetch_emails_error", error=str(e))
            return []

    async def acknowledge(self, source_id: str):
        """
        Mark email as read.

        Args:
            source_id: Email message ID
        """
        try:
            # For now, emails are already marked as read when fetched
            # Future: Could implement moving to "processed" folder
            logger.debug("email_acknowledged", message_id=source_id)

        except Exception as e:
            logger.error("acknowledge_email_error", message_id=source_id, error=str(e))

    async def match_organization(self, email_data: Dict) -> Optional[str]:
        """
        Match email TO address against organization email addresses.

        Args:
            email_data: Email data dict

        Returns:
            Organization slug if matched
        """
        to_address = email_data.get("to", "").lower()

        if not to_address:
            return None

        # Query organizations
        return await self._query_organization_by_email(to_address)

    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        """Connect to IMAP server."""
        try:
            mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            mail.login(self.imap_user, self.imap_password)
            logger.info("imap_connected", host=self.imap_host)
            return mail

        except Exception as e:
            logger.error("imap_connection_error", error=str(e))
            raise

    def _fetch_email(self, mail: imaplib.IMAP4_SSL, email_id: bytes) -> Optional[Dict]:
        """
        Fetch and parse single email.

        Args:
            mail: IMAP connection
            email_id: Email ID

        Returns:
            Dict with email data
        """
        try:
            status, msg_data = mail.fetch(email_id, '(RFC822)')

            if status != 'OK':
                return None

            # Parse email
            msg = email.message_from_bytes(msg_data[0][1])

            # Extract headers
            subject = self._decode_header(msg.get("Subject", ""))
            from_addr = parseaddr(msg.get("From", ""))[1]
            to_addr = parseaddr(msg.get("To", ""))[1]
            date = msg.get("Date", "")
            message_id = msg.get("Message-ID", str(email_id))

            # Extract body and attachments
            body_text = ""
            body_html = ""
            attachments = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    # Body text
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        body_text = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    elif content_type == "text/html" and "attachment" not in content_disposition:
                        body_html = part.get_payload(decode=True).decode("utf-8", errors="ignore")

                    # Attachments
                    elif "attachment" in content_disposition:
                        filename = part.get_filename()
                        if filename:
                            attachments.append({
                                "filename": self._decode_header(filename),
                                "content_type": content_type,
                                "data": part.get_payload(decode=True)
                            })
            else:
                # Single part message
                content_type = msg.get_content_type()
                if content_type == "text/plain":
                    body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                elif content_type == "text/html":
                    body_html = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            return {
                "message_id": message_id,
                "from": from_addr,
                "to": to_addr,
                "subject": subject,
                "date": date,
                "body_text": body_text,
                "body_html": body_html,
                "attachments": attachments
            }

        except Exception as e:
            logger.error("fetch_email_error", email_id=email_id.decode(), error=str(e))
            return None

    async def _aggregate_email_content(self, email_data: Dict) -> Dict[str, Any]:
        """
        Aggregate all email parts into unified structure for LLM.

        Args:
            email_data: Raw email data

        Returns:
            Dict with subject, body, attachments (with transcriptions)
        """
        content = {
            "subject": email_data.get("subject", ""),
            "body": email_data.get("body_text") or self._strip_html(email_data.get("body_html", "")),
            "attachments": []
        }

        # Process attachments
        for attachment in email_data.get("attachments", []):
            content_type = attachment.get("content_type", "")
            filename = attachment.get("filename", "unknown")
            data = attachment.get("data")

            # Audio files - transcribe
            if content_type.startswith("audio/"):
                try:
                    transcription = await self._transcribe_audio(data)
                    content["attachments"].append({
                        "type": "audio",
                        "filename": filename,
                        "transcription": transcription
                    })
                    logger.info("audio_transcribed", filename=filename)
                except Exception as e:
                    logger.error("audio_transcription_error", filename=filename, error=str(e))

            # Text files
            elif content_type.startswith("text/"):
                try:
                    text = data.decode("utf-8", errors="ignore")
                    content["attachments"].append({
                        "type": "text",
                        "filename": filename,
                        "text": text
                    })
                except Exception as e:
                    logger.error("text_extraction_error", filename=filename, error=str(e))

            # PDF, Word, etc. - future implementation
            # elif content_type == "application/pdf":
            #     text = extract_pdf_text(data)
            #     content["attachments"].append({"type": "text", "filename": filename, "text": text})

        return content

    async def _transcribe_audio(self, audio_data: bytes) -> str:
        """
        Transcribe audio using Whisper.

        Args:
            audio_data: Audio file bytes

        Returns:
            Transcription text
        """
        try:
            # Save to temporary file
            import tempfile
            import whisper

            with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            # Transcribe
            model = whisper.load_model("base")
            result = model.transcribe(tmp_path)

            # Cleanup
            import os
            os.unlink(tmp_path)

            return result["text"]

        except Exception as e:
            logger.error("whisper_transcription_error", error=str(e))
            return "[Transcription failed]"

    def _decode_header(self, header: str) -> str:
        """Decode email header."""
        if not header:
            return ""

        decoded_parts = decode_header(header)
        decoded_str = ""

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_str += part.decode(encoding or "utf-8", errors="ignore")
            else:
                decoded_str += part

        return decoded_str

    def _strip_html(self, html: str) -> str:
        """Strip HTML tags from text."""
        if not html:
            return ""

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n", strip=True)
