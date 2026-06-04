from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "change-this-secret-key-in-production"
    APP_DEBUG: bool = False
    APP_LOG_LEVEL: str = "INFO"
    APP_VERSION: str = "1.0.0"

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://aeaop:aeaop_secret@localhost:5432/aeaop"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 40
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_ECHO: bool = False

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: str = ""
    REDIS_SESSION_DB: int = 1
    REDIS_CACHE_DB: int = 2

    # ── Elasticsearch ────────────────────────────────────────────────────────
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    ELASTICSEARCH_USERNAME: str = ""
    ELASTICSEARCH_PASSWORD: str = ""
    ELASTICSEARCH_INDEX_PREFIX: str = "aeaop"

    # ── Qdrant ───────────────────────────────────────────────────────────────
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""

    # ── Kafka ────────────────────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_CONSUMER_GROUP: str = "aeaop-platform"

    # ── MinIO ────────────────────────────────────────────────────────────────
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "miniosecret"
    MINIO_SECURE: bool = False
    MINIO_BUCKET_CONFIGS: str = "aeaop-configs"
    MINIO_BUCKET_REPORTS: str = "aeaop-reports"
    MINIO_BUCKET_SNAPSHOTS: str = "aeaop-snapshots"
    MINIO_BUCKET_AUDIT: str = "aeaop-audit"

    # ── HashiCorp Vault ──────────────────────────────────────────────────────
    VAULT_ADDR: str = "http://localhost:8200"
    VAULT_TOKEN: str = ""
    VAULT_MOUNT_KV: str = "secret"
    VAULT_ROLE: str = "aeaop-platform"

    # ── Keycloak ─────────────────────────────────────────────────────────────
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "aeaop"
    KEYCLOAK_CLIENT_ID: str = "aeaop-backend"
    KEYCLOAK_CLIENT_SECRET: str = ""

    # ── AI / LLM ─────────────────────────────────────────────────────────────
    VLLM_BASE_URL: str = "http://localhost:8000/v1"
    VLLM_API_KEY: str = "no-key-required"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    LLM_PRIMARY_MODEL: str = "qwen3:72b"
    LLM_FAST_MODEL: str = "qwen3:14b"
    LLM_CODE_MODEL: str = "qwen2.5-coder:32b"
    LLM_VISION_MODEL: str = "qwen2.5vl:72b"
    LLM_EMBEDDING_MODEL: str = "nomic-embed-text:v2"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT_SECONDS: int = 120

    # ── SNMP ─────────────────────────────────────────────────────────────────
    SNMP_COMMUNITY: str = "public"
    SNMP_VERSION: str = "2c"
    SNMP_TIMEOUT: int = 5
    SNMP_RETRIES: int = 3
    SNMP_POLL_INTERVAL_SECONDS: int = 300

    # ── CORS ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    # ── Autonomy ─────────────────────────────────────────────────────────────
    AUTO_HEAL_ENABLED: bool = True
    AUTO_HEAL_MAX_RISK_LEVEL: str = "low"
    REQUIRE_APPROVAL_ABOVE: str = "low"

    # ── JWT ──────────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def kafka_servers_list(self) -> List[str]:
        return self.KAFKA_BOOTSTRAP_SERVERS.split(",")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
