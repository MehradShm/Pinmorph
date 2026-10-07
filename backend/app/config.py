from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.experiments.config import FeedConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

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
    sim_disposable: bool = False
    sim_environment_id: str | None = Field(
        default=None, pattern=r"^pinmorph-sim-[a-z0-9][a-z0-9-]{0,30}$"
    )
    sim_control_token: SecretStr | None = None
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

    @model_validator(mode="after")
    def simulation_requires_disposable_control(self):
        if self.sim_mode and (
            not self.sim_disposable
            or not self.sim_environment_id
            or not self.sim_control_token
            or len(self.sim_control_token.get_secret_value()) < 32
        ):
            raise ValueError(
                "SIM_MODE requires a disposable environment ID "
                "and a control token of at least 32 characters"
            )
        return self
