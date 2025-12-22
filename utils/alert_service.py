"""Simple alert service for semantika admin notifications.

Sends email alerts for critical system events (LLM credits, errors, etc.).
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Dict, Optional
import json

from .config import settings
from .logger import get_logger

logger = get_logger("alert_service")


class AlertService:
    """Simple email alert service with rate limiting."""
    
    def __init__(self):
        self.last_sent: Dict[str, datetime] = {}
        self.rate_limit_minutes = 60  # Don't send same alert more than once per hour
        
    def _should_send(self, alert_key: str) -> bool:
        """Check if enough time has passed since last alert of this type."""
        if alert_key not in self.last_sent:
            return True
            
        elapsed = datetime.utcnow() - self.last_sent[alert_key]
        return elapsed > timedelta(minutes=self.rate_limit_minutes)
    
    def _send_email(self, subject: str, body: str, context: Optional[Dict] = None):
        """Send email via SMTP."""
        try:
            # Skip if SMTP not configured
            if not settings.smtp_user or not settings.smtp_password:
                logger.warn("smtp_not_configured", message="Cannot send alert email")
                return
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[Semantika Alert] {subject}"
            msg['From'] = settings.smtp_user
            msg['To'] = settings.admin_email
            
            # Plain text version
            text_content = f"{body}\n\n"
            if context:
                text_content += f"Context:\n{json.dumps(context, indent=2)}\n"
            text_content += f"\nTimestamp: {datetime.utcnow().isoformat()}Z"
            
            msg.attach(MIMEText(text_content, 'plain'))
            
            # Send via SMTP
            if settings.smtp_secure:
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
                server.starttls()
            
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
            server.quit()
            
            logger.info("alert_email_sent", 
                subject=subject,
                to=settings.admin_email
            )
            
        except Exception as e:
            logger.error("alert_email_failed", 
                error=str(e),
                subject=subject
            )
    
    def llm_credits_exhausted(
        self, 
        provider: str,
        operation: str,
        error_message: str,
        remaining_tokens: Optional[int] = None
    ):
        """Alert: LLM provider out of credits."""
        alert_key = f"llm_credits_{provider}"
        
        if not self._should_send(alert_key):
            logger.debug("alert_rate_limited", alert_key=alert_key)
            return
        
        subject = f"⚠️ CRITICAL: {provider} credits exhausted"
        
        body = f"""LLM provider is out of credits and operations are failing.

Provider: {provider}
Operation: {operation}
Error: {error_message}
"""
        if remaining_tokens is not None:
            body += f"Remaining tokens: {remaining_tokens}\n"
        
        body += f"""
Action required:
1. Go to {provider} dashboard and add credits
2. Check https://openrouter.ai/settings/keys (if OpenRouter)
3. Operations will resume automatically once credits are added
"""
        
        context = {
            "provider": provider,
            "operation": operation,
            "error": error_message,
            "remaining_tokens": remaining_tokens
        }
        
        self._send_email(subject, body, context)
        self.last_sent[alert_key] = datetime.utcnow()
        
        logger.warn("llm_credits_alert_sent",
            provider=provider,
            operation=operation
        )
    
    def scraping_failed(
        self,
        source_name: str,
        url: str,
        error: str,
        consecutive_failures: int = 1
    ):
        """Alert: Source scraping failed multiple times."""
        alert_key = f"scraping_failed_{source_name}"
        
        # Only alert after 3+ consecutive failures
        if consecutive_failures < 3:
            return
        
        if not self._should_send(alert_key):
            logger.debug("alert_rate_limited", alert_key=alert_key)
            return
        
        subject = f"⚠️ WARNING: Scraping failed for {source_name}"
        
        body = f"""Source scraping has failed {consecutive_failures} times consecutively.

Source: {source_name}
URL: {url}
Error: {error}

Action required:
1. Check if source website is down or changed structure
2. Review scraping configuration in database
3. Update scraper workflow if needed
"""
        
        context = {
            "source_name": source_name,
            "url": url,
            "error": error,
            "consecutive_failures": consecutive_failures
        }
        
        self._send_email(subject, body, context)
        self.last_sent[alert_key] = datetime.utcnow()
        
        logger.warn("scraping_failure_alert_sent",
            source_name=source_name,
            consecutive_failures=consecutive_failures
        )


# Global singleton
_alert_service: Optional[AlertService] = None


def get_alert_service() -> AlertService:
    """Get or create alert service singleton."""
    global _alert_service
    if _alert_service is None:
        _alert_service = AlertService()
    return _alert_service


# Convenience alias
alert = get_alert_service()
