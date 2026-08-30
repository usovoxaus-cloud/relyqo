import os


def postgres_url(value: str) -> str:
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+psycopg://", 1)
    return value


class Settings:
    """Environment configuration without runtime schema coercion."""

    def __init__(self):
        self.database_url = postgres_url(
            os.getenv("DATABASE_URL", "sqlite:///./relyqo.db")
        )
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.qr_secret = os.getenv("QR_SECRET", "development-secret-change-me-32chars")
        self.owner_password = os.getenv("OWNER_PASSWORD") or None
        self.review_password = os.getenv("REVIEW_PASSWORD") or None
        self.public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
        self.demo_mode = os.getenv("DEMO_MODE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:8000")


settings = Settings()
