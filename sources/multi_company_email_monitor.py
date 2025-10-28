"""Multi-company email monitor for semantika.

Monitors email addresses in the format p.{company_code}@ekimen.ai
and routes emails to appropriate company workflows.

Example routing:
- p.elconfidencial@ekimen.ai → El Confidencial company
- p.lavanguardia@ekimen.ai → La Vanguardia company  
- p.demo@ekimen.ai → Demo company
"""

import imaplib
import email
from email.header import decode_header
from typing import List, Dict, Optional, Tuple
import asyncio
import tempfile
import os
import re

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from .audio_transcriber import AudioTranscriber

logger = get_logger("multi_company_email_monitor")


class MultiCompanyEmailMonitor:
    """Monitor multiple company email addresses via aliases."""

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
        Initialize multi-company email monitor.

        Args:
            imap_server: IMAP server address
            imap_port: IMAP server port (usually 993 for SSL)
            email_address: Main email address (e.g., contact@ekimen.ai)
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
            "multi_company_email_monitor_initialized",
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

    def _extract_company_from_to_header(self, to_header: str) -> Optional[str]:
        """
        Extract company code from To header.

        Expected format: p.{company_code}@ekimen.ai
        Examples:
        - p.elconfidencial@ekimen.ai → elconfidencial
        - p.demo@ekimen.ai → demo
        - contact@ekimen.ai → None (not a company alias)

        Args:
            to_header: Email To header

        Returns:
            Company code or None
        """
        try:
            # Pattern to match p.{company_code}@ekimen.ai
            pattern = r'p\.([a-zA-Z0-9\-_]+)@ekimen\.ai'
            
            match = re.search(pattern, to_header, re.IGNORECASE)
            if match:
                company_code = match.group(1)
                logger.debug("company_extracted", to_header=to_header, company_code=company_code)
                return company_code
            
            logger.debug("no_company_in_to_header", to_header=to_header)
            return None

        except Exception as e:
            logger.debug("company_extraction_failed", to_header=to_header, error=str(e))
            return None

    async def _get_company_and_organization(self, company_code: str) -> Optional[Tuple[Dict, Dict]]:
        """
        Get company and organization by company code.

        Args:
            company_code: Company code (e.g., 'elconfidencial', 'demo')

        Returns:
            Tuple of (company, organization) or None if not found
        """
        try:
            supabase = get_supabase_client()
            
            # Get company by code
            company_result = supabase.client.table("companies")\
                .select("*")\
                .eq("company_code", company_code)\
                .eq("is_active", True)\
                .maybe_single()\
                .execute()
            
            if not company_result.data:
                logger.warn("company_not_found", company_code=company_code)
                return None
            
            company = company_result.data
            
            # Get first active organization for this company
            org_result = supabase.client.table("organizations")\
                .select("*")\
                .eq("company_id", company["id"])\
                .eq("is_active", True)\
                .limit(1)\
                .execute()
            
            if not org_result.data:
                logger.warn("no_organization_for_company", company_code=company_code)
                return None
            
            organization = org_result.data[0]
            
            logger.debug("company_and_org_found", 
                company_code=company_code,
                company_id=company["id"],
                org_slug=organization["slug"]
            )
            
            return company, organization

        except Exception as e:
            logger.error("company_org_lookup_error", company_code=company_code, error=str(e))
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

    async def _process_email_body_with_workflow(
        self,
        body: str,
        subject: str,
        company: Dict,
        organization: Dict
    ):
        """
        Process email body using company-specific workflow.

        Args:
            body: Email body
            subject: Email subject
            company: Company data
            organization: Organization data
        """
        try:
            if not body.strip():
                return

            logger.info("processing_email_body_with_workflow", 
                subject=subject,
                company_code=company["company_code"]
            )

            # PHASE 3: Use workflow factory for company-specific processing
            from workflows.workflow_factory import get_workflow
            from core.source_content import SourceContent
            
            # Create SourceContent for email
            source_content = SourceContent(
                source_type="email",
                source_id=f"email_{hash(subject + body[:100])}",
                organization_slug=organization["slug"],
                text_content=body,
                metadata={
                    "subject": subject,
                    "source": "email",
                    "company_code": company["company_code"]
                }
            )
            
            # Get company-specific workflow
            workflow = get_workflow(company["company_code"], company.get("settings", {}))
            
            # Process content through workflow
            result = await workflow.process_content(source_content)
            
            # Save context unit to database
            context_unit = result.get("context_unit", {})
            if context_unit:
                supabase = get_supabase_client()
                
                # Prepare context unit data for database
                context_unit_data = {
                    "id": context_unit.get("id"),
                    "organization_id": organization["id"],
                    "company_id": company["id"],
                    "source_type": "email",
                    "source_id": source_content.source_id,
                    "source_metadata": source_content.metadata,
                    "title": context_unit.get("title"),
                    "summary": context_unit.get("summary"),
                    "tags": context_unit.get("tags", []),
                    "atomic_statements": context_unit.get("atomic_statements", []),
                    "raw_text": context_unit.get("raw_text", source_content.text_content),
                    "status": "completed",
                    "processed_at": "now()"
                }
                
                # Insert into press_context_units
                db_result = supabase.client.table("press_context_units").insert(context_unit_data).execute()
                
                logger.info(
                    "context_unit_saved_to_db",
                    context_unit_id=context_unit.get("id"),
                    company_code=company["company_code"]
                )
            
            logger.info(
                "email_body_processed_with_workflow",
                subject=subject,
                company_code=company["company_code"],
                context_unit_id=result.get("context_unit", {}).get("id")
            )

        except Exception as e:
            logger.error("email_body_workflow_processing_error", 
                subject=subject, 
                company_code=company.get("company_code"),
                error=str(e)
            )

    async def _process_text_attachment_with_workflow(
        self,
        filename: str,
        content: bytes,
        subject: str,
        company: Dict,
        organization: Dict
    ):
        """
        Process text attachment using company workflow.

        Args:
            filename: Attachment filename
            content: Attachment bytes
            subject: Email subject
            company: Company data
            organization: Organization data
        """
        try:
            logger.info("processing_text_attachment_with_workflow", 
                filename=filename,
                company_code=company["company_code"]
            )

            # Decode text
            text = content.decode("utf-8", errors="ignore")

            # Create SourceContent for attachment
            from workflows.workflow_factory import get_workflow
            from core.source_content import SourceContent
            
            source_content = SourceContent(
                source_type="email_attachment",
                source_id=f"attachment_{hash(filename + text[:100])}",
                organization_slug=organization["slug"],
                text_content=text,
                metadata={
                    "filename": filename,
                    "email_subject": subject,
                    "source": "email_attachment",
                    "company_code": company["company_code"]
                }
            )
            
            # Get company-specific workflow
            workflow = get_workflow(company["company_code"], company.get("settings", {}))
            
            # Process content through workflow
            result = await workflow.process_content(source_content)

            logger.info(
                "text_attachment_processed_with_workflow",
                filename=filename,
                company_code=company["company_code"],
                context_unit_id=result.get("context_unit", {}).get("id")
            )

        except Exception as e:
            logger.error("text_attachment_workflow_processing_error", 
                filename=filename,
                company_code=company.get("company_code"),
                error=str(e)
            )

    async def _process_audio_attachment_with_workflow(
        self,
        filename: str,
        content: bytes,
        subject: str,
        company: Dict,
        organization: Dict
    ):
        """
        Process audio attachment with transcription and workflow.

        Args:
            filename: Attachment filename
            content: Attachment bytes
            subject: Email subject
            company: Company data
            organization: Organization data
        """
        try:
            logger.info("processing_audio_attachment_with_workflow", 
                filename=filename,
                company_code=company["company_code"]
            )

            # Save to temporary file for transcription
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name

            try:
                # Transcribe audio
                transcription_result = self.transcriber.transcribe_file(tmp_path)
                
                if not transcription_result.get("text"):
                    logger.warn("empty_transcription", filename=filename)
                    return

                # Create SourceContent for transcribed audio
                from workflows.workflow_factory import get_workflow
                from core.source_content import SourceContent
                
                source_content = SourceContent(
                    source_type="email_audio",
                    source_id=f"audio_{hash(filename + transcription_result['text'][:100])}",
                    organization_slug=organization["slug"],
                    text_content=transcription_result["text"],
                    metadata={
                        "filename": filename,
                        "email_subject": subject,
                        "source": "email_audio",
                        "company_code": company["company_code"],
                        "transcription_language": transcription_result.get("language", "unknown"),
                        "audio_duration": transcription_result.get("duration", 0)
                    }
                )
                
                # Get company-specific workflow
                workflow = get_workflow(company["company_code"], company.get("settings", {}))
                
                # Process content through workflow
                result = await workflow.process_content(source_content)

                logger.info(
                    "audio_attachment_processed_with_workflow",
                    filename=filename,
                    company_code=company["company_code"],
                    context_unit_id=result.get("context_unit", {}).get("id"),
                    transcribed_length=len(transcription_result["text"])
                )

            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        except Exception as e:
            logger.error("audio_attachment_workflow_processing_error", 
                filename=filename,
                company_code=company.get("company_code"),
                error=str(e)
            )

    async def _process_email(self, mail: imaplib.IMAP4_SSL, email_id: bytes):
        """
        Process a single email with multi-company routing.

        Args:
            mail: IMAP connection
            email_id: Email ID
        """
        try:
            # Fetch email
            _, msg_data = mail.fetch(email_id, "(RFC822)")
            email_body = msg_data[0][1]
            message = email.message_from_bytes(email_body)

            # Get headers
            subject = self._decode_subject(message.get("Subject", "No Subject"))
            to_header = message.get("To", "")
            from_header = message.get("From", "")

            logger.info("processing_email_multi_company", 
                subject=subject,
                to=to_header,
                from_addr=from_header
            )

            # Extract company code from To header
            company_code = self._extract_company_from_to_header(to_header)

            if not company_code:
                logger.warn(
                    "no_company_in_email",
                    to_header=to_header,
                    subject=subject,
                    expected_format="p.{company_code}@ekimen.ai"
                )
                # Mark as read and skip
                mail.store(email_id, "+FLAGS", "\\Seen")
                return

            # Get company and organization
            company_org = await self._get_company_and_organization(company_code)
            if not company_org:
                logger.warn("company_not_found_for_code", 
                    company_code=company_code,
                    subject=subject
                )
                mail.store(email_id, "+FLAGS", "\\Seen")
                return

            company, organization = company_org

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
                await self._process_email_body_with_workflow(body, subject, company, organization)

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
                        await self._process_text_attachment_with_workflow(
                            filename, content, subject, company, organization
                        )
                    elif extension in self.AUDIO_EXTENSIONS:
                        await self._process_audio_attachment_with_workflow(
                            filename, content, subject, company, organization
                        )
                    else:
                        logger.debug("unsupported_attachment", 
                            filename=filename,
                            company_code=company_code
                        )

            # Mark as read
            mail.store(email_id, "+FLAGS", "\\Seen")

            logger.info("email_processed_multi_company", 
                subject=subject,
                company_code=company_code
            )

        except Exception as e:
            logger.error("email_processing_error_multi_company", error=str(e))

    async def check_inbox(self):
        """Check inbox for new unread emails."""
        try:
            mail = self._connect()

            # Search for unread emails
            _, search_data = mail.search(None, "UNSEEN")
            email_ids = search_data[0].split()

            logger.info("inbox_checked_multi_company", unread_count=len(email_ids))

            # Process each email
            for email_id in email_ids:
                await self._process_email(mail, email_id)

            # Logout
            mail.logout()

        except Exception as e:
            logger.error("inbox_check_error_multi_company", error=str(e))

    async def start(self):
        """Start monitoring email inbox for multiple companies."""
        logger.info("multi_company_email_monitor_started", email=self.email_address)

        while True:
            try:
                await self.check_inbox()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error("monitor_loop_error_multi_company", error=str(e))
                await asyncio.sleep(self.check_interval)