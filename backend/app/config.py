from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.experiments.config import FeedConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://pinmorph:pinmorph-local@127.0.0.1:15432/pinmorph"
    )
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:16379/0")
    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_access_key: str = "pinmorph"
    s3_secret_key: SecretStr = SecretStr("pinmorph-local-storage")
    s3_bucket: str = "pinmorph-media"
    log_level: str = "INFO"
    sim_mode: bool = False
    feed_config: FeedConfig = Field(default_factory=FeedConfig)
    health_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    upload_max_bytes: int = 12 * 1024 * 1024
    image_max_pixels: int = 24_000_000
    session_days: int = 7
    cookie_secure: bool = False  # Enable when serving over HTTPS.
    trusted_origins: list[str] = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
