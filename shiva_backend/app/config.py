from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields in .env file
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./shiva_support.db"
    
    # PostgreSQL connection pool settings
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600
    
    # Testing database override (used by pytest)
    test_database_url: str = "sqlite+aiosqlite:///:memory:"

    # Customer API
    customer_api_key: str = "test_key"
    customer_api_base_url: str = "https://api.test.com"

    # Qdrant - Local configuration
    qdrant_url: str = "http://localhost:6333"  # Local Qdrant instance
    qdrant_api_key: Optional[str] = None  # Not needed for local instance
    qdrant_collection_name: str = "knowledge_base"
    qdrant_similarity_threshold: float = 0.75
    
    # Multiple Knowledge Bases - mapped to customer applications
    qdrant_collections: dict = {
        "default": "knowledge_base",
        "shiva_support": "shiva_support_kb",
        "shiva_analytics": "shiva_analytics_kb",
        "shiva_crm": "shiva_crm_kb",
        "shiva_erp": "shiva_erp_kb",
        "shiva_payments": "shiva_payments_kb",
        "shiva_integrations": "shiva_integrations_kb",
        "shiva_mobile": "shiva_mobile_kb",
        "shiva_api": "shiva_api_kb"
    }
    
    # KB Selection Rules - based on customer application
    kb_selection_rules: dict = {
        "application_based": {
            "shiva_support": "shiva_support_kb",
            "shiva_analytics": "shiva_analytics_kb",
            "shiva_crm": "shiva_crm_kb",
            "shiva_erp": "shiva_erp_kb",
            "shiva_payments": "shiva_payments_kb",
            "shiva_integrations": "shiva_integrations_kb",
            "shiva_mobile": "shiva_mobile_kb",
            "shiva_api": "shiva_api_kb"
        }
    }

    # Groq
    groq_api_key: str = "test_groq_key"
    groq_model: str = "openai/gpt-oss-20b"

    # Gemini (for complex tasks)
    gemini_api_key: Optional[str] = None  # Optional: if not set, complex tasks fall back to Groq
    gemini_model: str = "gemini-1.5-pro"
    gemini_complexity_threshold: float = 0.7  # Lower than escalation threshold (0.8) to use Gemini for borderline complex cases

    # Codex
    codex_api_key: str = "test_codex_key"
    codex_model: str = "gpt-4-codex"

    # Auth
    jwt_secret_key: str = "test_jwt_secret"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60

    # Rate Limiting
    rate_limit_per_customer: int = 100
    rate_limit_per_ip: int = 50
    rate_limit_window_seconds: int = 60

    # AI Routing
    support_ai_confidence_threshold: float = 0.3  # Very low threshold to prioritize giving solutions over escalation
    code_ai_enabled: bool = True
    max_ai_attempts_before_escalation: int = 5  # More attempts before escalation to reduce user frustration
    # Staff member used by the demo/default routing policy when a complex chat is escalated.
    # Production deployments can replace this with workload-based staff assignment.
    default_escalation_staff_id: str = "staff_001"

    # Conversation History Management
    max_history_turns: int = 10  # Maximum number of full turns to send before summarizing
    keep_recent_turns: int = 4   # Number of most recent turns to keep verbatim when summarizing

    # Optional SMTP configuration for customer reply notifications.
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_email: str = "support@shiva.local"
    smtp_use_tls: bool = True

    # Upload
    max_upload_size_mb: int = 10
    upload_dir: str = "./uploads"

    # Logging
    log_level: str = "INFO"


settings = Settings()
