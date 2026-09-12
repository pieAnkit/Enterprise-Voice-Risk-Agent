"""Central settings — everything env-driven, 12-factor style."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_env: str = "dev"
    base_url: str = "https://your-public-domain.com"

    # OpenAI (embeddings for RAG; voice model runs inside Vapi)
    openai_api_key: str | None = None

    # Vapi — assistant calls our tools over HTTPS
    vapi_api_key: str | None = None
    vapi_assistant_id: str | None = None
    vapi_phone_number_id: str | None = None
    oncall_number: str | None = None  # E.164, e.g. +14155551234
    vapi_webhook_secret: str | None = None  # HMAC verification

    # UpGuard cybersecurity API — OAuth 2.0 client credentials
    upguard_token_url: str = "https://api.upguard.com/oauth/token"
    upguard_client_id: str | None = None
    upguard_client_secret: str | None = None
    upguard_api_base: str = "https://api.upguard.com/api/public"
    risk_cache_ttl_seconds: int = 300  # 5-min freshness on risk profile

    # Infra
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/voice_agent"
    redis_url: str = "redis://localhost:6379/0"

    # Pinecone (RAG over historical findings)
    pinecone_api_key: str | None = None
    pinecone_index: str = "security-findings"

    class Config:
        env_file = ".env"


settings = Settings()
