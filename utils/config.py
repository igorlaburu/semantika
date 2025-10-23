"""Configuration management using Pydantic settings.

All configuration is loaded from environment variables (.env file).
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Supabase Configuration
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_key: str = Field(..., description="Supabase service role key")

    # Qdrant Configuration
    qdrant_url: str = Field(
        default="http://qdrant:6333",
        description="Qdrant server URL"
    )
    qdrant_api_key: str = Field(
        default="",
        description="Qdrant API key (for Qdrant Cloud)"
    )
    qdrant_collection_name: str = Field(
        default="semantika_prod",
        description="Qdrant collection name"
    )

    # OpenRouter Configuration
    openrouter_api_key: str = Field(..., description="OpenRouter API key")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenRouter base URL"
    )
    openrouter_default_model: str = Field(
        default="anthropic/claude-3.5-sonnet",
        description="Default model for complex tasks"
    )
    openrouter_fast_model: str = Field(
        default="openai/gpt-4o-mini",
        description="Fast model for simple tasks"
    )

    # ScraperTech Configuration (Twitter)
    scrapertech_api_key: str = Field(
        default="",
        description="ScraperTech API key for Twitter scraping"
    )
    scrapertech_base_url: str = Field(
        default="https://api.scraper.tech",
        description="ScraperTech API base URL"
    )

    # Text Processing Configuration
    chunk_size: int = Field(
        default=1000,
        description="Size of text chunks for embedding"
    )
    chunk_overlap: int = Field(
        default=200,
        description="Overlap between chunks"
    )
    similarity_threshold: float = Field(
        default=0.98,
        description="Threshold for duplicate detection"
    )

    # TTL Configuration
    data_ttl_days: int = Field(
        default=30,
        description="Days before non-special data is deleted"
    )

    # Server Configuration
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    log_level: str = Field(default="INFO", description="Logging level")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


# Global settings instance
settings = Settings()
