"""Sources module for semantika.

Handles data ingestion from multiple sources:
- Web scraping with LLM extraction
- File monitoring (documents and audio)
- Email monitoring (IMAP)
- Twitter scraping (placeholder for future)
- API connectors (placeholder for future)
"""

from .web_scraper import WebScraper
from .audio_transcriber import AudioTranscriber
from .file_monitor import FileMonitor
from .email_monitor import EmailMonitor

# Placeholders - not yet implemented
# from .twitter_scraper import TwitterScraper
# from .api_connectors import EFEConnector, ReutersConnector, WordPressConnector

__all__ = [
    "WebScraper",
    "AudioTranscriber",
    "FileMonitor",
    "EmailMonitor",
]
