from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./relyqo.db"
    redis_url: str = "redis://localhost:6379/0"
    qr_secret: str = "development-secret-change-me-32chars"
    public_base_url: str = "http://localhost:8000"
    demo_mode: bool = True
    cors_origins: str = "http://localhost:8000"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
