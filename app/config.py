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
        if os.getenv("RENDER") and not os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("Render requires a persistent PostgreSQL DATABASE_URL")
        self.database_url = postgres_url(
            os.getenv("DATABASE_URL", "sqlite:///./relyqo.db")
        )
        self.resend_api_key = os.getenv("RESEND_API_KEY", "")
        self.sms_provider = os.getenv("SMS_PROVIDER", "twilio").strip().lower()
        self.eskiz_email = os.getenv("ESKIZ_EMAIL", "")
        self.eskiz_password = os.getenv("ESKIZ_PASSWORD", "")
        self.eskiz_sender = os.getenv("ESKIZ_SENDER", "4546")
        self.eskiz_message_template = os.getenv("ESKIZ_MESSAGE_TEMPLATE", "")
        self.sms_otp_secret = os.getenv("SMS_OTP_SECRET", "")
        self.twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.twilio_verify_service_sid = os.getenv("TWILIO_VERIFY_SERVICE_SID", "")
        # Enable countries explicitly after checking provider coverage and costs.
        self.sms_allowed_regions = os.getenv("SMS_ALLOWED_REGIONS", "")
        self.recovery_email_from = os.getenv("RECOVERY_EMAIL_FROM", "")
        self.recovery_allow_local_urls = (
            os.getenv("RECOVERY_ALLOW_LOCAL_URLS", "false").lower() == "true"
        )
        self.automatic_backup_status = os.getenv(
            "AUTOMATIC_BACKUP_STATUS", "not_configured"
        )
        self.database_expires_at = os.getenv("DATABASE_EXPIRES_AT", "")
        self.database_plan = os.getenv("DATABASE_PLAN", "unknown").strip().lower()
        self.backup_recovery_days = os.getenv("BACKUP_RECOVERY_DAYS", "")
        self.hosting_checked_at = os.getenv("HOSTING_CHECKED_AT", "")
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.qr_secret = os.getenv("QR_SECRET", "development-secret-change-me-32chars")
        self.owner_password = os.getenv("OWNER_PASSWORD") or None
        self.owner_email = (os.getenv("OWNER_EMAIL") or "").strip().lower() or None
        self.review_password = os.getenv("REVIEW_PASSWORD") or None
        self.admin_password = os.getenv("ADMIN_PASSWORD") or None
        self.openai_api_key = os.getenv("OPENAI_API_KEY") or None
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
        self.google_maps_browser_key = os.getenv("GOOGLE_MAPS_BROWSER_KEY") or None
        self.public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
        self.demo_mode = os.getenv("DEMO_MODE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:8000")


settings = Settings()
