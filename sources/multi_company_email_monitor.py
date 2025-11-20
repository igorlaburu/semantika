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
from typing import List, Dict, Optional, Tuple, Any
import asyncio
import tempfile
import os
import re

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.unified_context_verifier import verify_novelty
from utils.unified_context_ingester import ingest_context_unit
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

    async def _get_routing_and_source(self, to_address: str) -> Optional[Tuple[Dict, Dict, Dict]]:
        """
        Get routing configuration and associated source for email address.

        Args:
            to_address: Full email address (e.g., 'p.demo@ekimen.ai' or '"name" <p.demo@ekimen.ai>')

        Returns:
            Tuple of (company, organization, source) or None if not found
        """
        try:
            supabase = get_supabase_client()
            
            # Extract clean email address from formats like '"name" <email@domain.com>'
            email_pattern = r'<([^>]+)>|([^\s<>]+@[^\s<>]+)'
            email_match = re.search(email_pattern, to_address)
            clean_email = email_match.group(1) or email_match.group(2) if email_match else to_address
            
            # Get email routing configuration with associated press source
            routing = await supabase.get_email_routing_for_address(clean_email)
            
            if not routing:
                logger.warn("no_routing_found", to_address=to_address, clean_email=clean_email)
                return None
            
            # Extract source from routing
            source = routing.get("sources")
            if not source:
                logger.warn("no_source_in_routing", to_address=to_address)
                return None
            
            # Get company
            company_result = supabase.client.table("companies")\
                .select("*")\
                .eq("id", source["company_id"])\
                .eq("is_active", True)\
                .maybe_single()\
                .execute()
            
            if not company_result.data:
                logger.warn("company_not_found", company_id=source["company_id"])
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
                logger.warn("no_organization_for_company", company_id=company["id"])
                return None
            
            organization = org_result.data[0]
            
            logger.debug("routing_and_source_found", 
                to_address=to_address,
                company_id=company["id"],
                source_id=source["source_id"],
                org_slug=organization["slug"]
            )
            
            return company, organization, source

        except Exception as e:
            logger.error("routing_lookup_error", to_address=to_address, error=str(e))
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
            
            # Get workflow for this source
            workflow_code = source.get("workflow_code", "default")
            workflow = get_workflow(workflow_code, company.get("settings", {}))
            
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
            
            # Get workflow for this source
            workflow_code = source.get("workflow_code", "default")
            workflow = get_workflow(workflow_code, company.get("settings", {}))
            
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

                # Save context unit to database
                context_unit = result.get("context_unit", {})
                if context_unit:
                    supabase = get_supabase_client()
                    
                    # Prepare context unit data for database
                    context_unit_data = {
                        "id": context_unit.get("id"),
                        "organization_id": organization["id"],
                        "company_id": company["id"],
                        "source_type": "email_audio",
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
                        "audio_context_unit_saved_to_db",
                        context_unit_id=context_unit.get("id"),
                        company_code=company["company_code"],
                        filename=filename
                    )

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

    async def _process_combined_content_with_workflow(
        self,
        content_parts: List[str],
        subject: str,
        company: Dict,
        organization: Dict,
        message_id: str,
        source: Dict,
        source_metadata: Dict
    ):
        """
        Process combined email content (body + attachments) as single context unit.

        Args:
            content_parts: List of content parts (subject, body, attachments, transcriptions)
            subject: Email subject
            company: Company data
            organization: Organization data
            source_metadata: Additional metadata
        """
        try:
            logger.info("processing_combined_email_content_with_workflow", 
                subject=subject,
                company_code=company["company_code"],
                content_parts_count=len(content_parts)
            )

            # Combine all content into single text
            combined_text = "\n\n".join(content_parts)
            
            # Create SourceContent for combined content
            from workflows.workflow_factory import get_workflow
            from core.source_content import SourceContent
            
            source_content = SourceContent(
                source_type="email",
                source_id=f"email_{hash(subject + combined_text[:100])}",
                organization_slug=organization["slug"],
                text_content=combined_text,
                metadata=source_metadata,
                title=subject or "(Sin asunto)"
            )
            
            # Get workflow for this source from metadata
            workflow_code = source_metadata.get("workflow_code", "default")
            workflow = get_workflow(workflow_code, company.get("settings", {}))
            
            # Process content through workflow
            result = await workflow.process_content(source_content)
            
            # Phase 1: Verify novelty using Message-ID
            verification_result = await verify_novelty(
                source_type="email",
                content_data={
                    "message_id": message_id,
                    "subject": subject,
                    "source_id": source["source_id"]
                },
                company_id=company["id"]
            )

            if not verification_result["is_novel"]:
                logger.info("email_duplicate_skipped",
                    subject=subject[:50],
                    message_id=message_id,
                    reason=verification_result["reason"],
                    duplicate_id=verification_result.get("duplicate_id")
                )
                return

            # Phase 2: Ingest context unit with unified ingester
            ingest_result = await ingest_context_unit(
                # Pre-generated field from email
                title=subject or "(Sin asunto)",
                raw_text=combined_text,

                # LLM will generate: summary, tags, category, atomic_statements
                # (Uses GPT-4o-mini via unified_context_ingester)

                # Required metadata
                company_id=company["id"],
                source_type="email",
                source_id=source["source_id"],

                # Optional metadata
                source_metadata={
                    **source_metadata,
                    "organization_id": organization["id"],
                    "message_id": message_id,
                    "from": source_metadata.get("from"),
                    "combined_content": True
                },

                # Control flags
                generate_embedding_flag=True,
                check_duplicates=True
            )

            if ingest_result["success"]:
                logger.info("email_combined_content_ingested",
                    subject=subject[:50],
                    context_unit_id=ingest_result["context_unit_id"],
                    generated_fields=ingest_result.get("generated_fields", []),
                    raw_text_length=len(combined_text)
                )
            elif ingest_result.get("duplicate"):
                logger.info("email_duplicate_semantic",
                    subject=subject[:50],
                    duplicate_id=ingest_result.get("duplicate_id"),
                    similarity=ingest_result.get("similarity")
                )
            else:
                logger.error("email_ingest_failed",
                    subject=subject[:50],
                    error=ingest_result.get("error")
                )
            
            logger.info(
                "combined_email_content_processed_with_workflow",
                subject=subject,
                company_code=company["company_code"],
                context_unit_id=ingest_result.get("context_unit_id") if ingest_result["success"] else None
            )

            # Log execution
            supabase = get_supabase_client()
            await supabase.log_execution(
                client_id=source_metadata.get("client_id", "00000000-0000-0000-0000-000000000000"),
                company_id=company["id"],
                source_name=source_metadata.get("source_name", company["company_name"]),
                source_type="email",
                items_count=1,
                status_code=200,
                status="success",
                details=f"Email procesado: {subject}",
                metadata={
                    "subject": subject,
                    "workflow_code": workflow_code,
                    "context_unit_id": ingest_result.get("context_unit_id") if ingest_result["success"] else None,
                    "content_parts": len(content_parts),
                    "source_id": source_metadata.get("source_id")
                },
                workflow_code=workflow_code
            )

        except Exception as e:
            logger.error("combined_content_workflow_processing_error", 
                subject=subject, 
                company_code=company.get("company_code"),
                error=str(e)
            )
            
            # Log failed execution
            try:
                workflow_code = source_metadata.get("workflow_code", "default")
                await supabase.log_execution(
                    client_id=source_metadata.get("client_id", "00000000-0000-0000-0000-000000000000"),
                    company_id=company.get("id"),
                    source_name=source_metadata.get("source_name", company.get("company_name", "Unknown")),
                    source_type="email",
                    items_count=0,
                    status_code=500,
                    status="error",
                    details=f"Error procesando email: {subject}",
                    error_message=str(e),
                    metadata={
                        "subject": subject,
                        "workflow_code": workflow_code,
                        "error_type": type(e).__name__,
                        "source_id": source_metadata.get("source_id")
                    },
                    workflow_code=workflow_code
                )
            except Exception as log_error:
                logger.error("execution_log_error", error=str(log_error))

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
            message_id = message.get("Message-ID", str(email_id.decode() if isinstance(email_id, bytes) else email_id))

            logger.info("processing_email_multi_company", 
                subject=subject,
                to=to_header,
                from_addr=from_header
            )

            # Get routing configuration and source for this email address
            routing_result = await self._get_routing_and_source(to_header)
            if not routing_result:
                logger.warn(
                    "no_routing_for_email",
                    to_header=to_header,
                    subject=subject,
                    message="Email routing not configured for this address"
                )
                # Mark as read and skip
                mail.store(email_id, "+FLAGS", "\\Seen")
                return

            company, organization, source = routing_result

            # Collect all content (email body + attachments) into one context unit
            all_content_parts = []
            
            # Add subject
            if subject.strip():
                all_content_parts.append(f"Asunto: {subject}")
            
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
                all_content_parts.append(body.strip())

            # Process attachments and collect their content
            audio_transcriptions = []
            text_attachments = []
            
            if message.is_multipart():
                for part in message.walk():
                    # Skip non-attachments
                    if part.get_content_maintype() == "multipart":
                        continue
                    
                    # Debug: log all parts to understand email structure
                    logger.debug("email_part_detected",
                        content_type=part.get_content_type(),
                        content_disposition=part.get("Content-Disposition"),
                        filename=part.get_filename(),
                        company_code=company["company_code"]
                    )
                    
                    if part.get("Content-Disposition") is None:
                        continue

                    filename = part.get_filename()
                    if not filename:
                        continue

                    # Get file extension
                    extension = os.path.splitext(filename)[1].lower()
                    content = part.get_payload(decode=True)

                    if extension in self.TEXT_EXTENSIONS:
                        text_content = content.decode("utf-8", errors="ignore")
                        text_attachments.append(f"Archivo adjunto '{filename}':\n{text_content}")
                        
                    elif extension in self.AUDIO_EXTENSIONS:
                        # Transcribe audio
                        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
                            tmp_file.write(content)
                            tmp_path = tmp_file.name
                        
                        try:
                            transcription_result = self.transcriber.transcribe_file(tmp_path)
                            if transcription_result.get("text"):
                                audio_transcriptions.append(f"Transcripción del audio '{filename}':\n{transcription_result['text']}")
                        except Exception as e:
                            logger.error("audio_transcription_error", filename=filename, error=str(e))
                        finally:
                            if os.path.exists(tmp_path):
                                os.unlink(tmp_path)
                    else:
                        logger.debug("unsupported_attachment", 
                            filename=filename,
                            company_code=company["company_code"]
                        )
            
            # Add all text attachments
            for text_attachment in text_attachments:
                all_content_parts.append(text_attachment)
                
            # Add all audio transcriptions
            for audio_transcription in audio_transcriptions:
                all_content_parts.append(audio_transcription)
            
            # Create single context unit with all content
            if all_content_parts:
                await self._process_combined_content_with_workflow(
                    all_content_parts, subject, company, organization,
                    message_id=message_id,
                    source=source,
                    source_metadata={
                        "subject": subject,
                        "company_code": company["company_code"],
                        "client_id": source["client_id"],
                        "source_id": source["source_id"],
                        "source_name": source["source_name"],
                        "workflow_code": source.get("workflow_code", "default"),
                        "attachments_count": len(text_attachments) + len(audio_transcriptions),
                        "message_id": message_id
                    }
                )

            # Mark as read
            mail.store(email_id, "+FLAGS", "\\Seen")

            logger.info("email_processed_multi_company", 
                subject=subject,
                company_code=company["company_code"]
            )

        except Exception as e:
            logger.error("email_processing_error_multi_company", 
                error=str(e),
                subject=subject if 'subject' in locals() else "unknown"
            )

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