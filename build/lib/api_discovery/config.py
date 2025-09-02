from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="API_DISCOVERY_",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    verify_tls: bool = Field(default=True, env="VERIFY_TLS")
    request_timeout_seconds: float = Field(default=30.0, env="REQUEST_TIMEOUT_SECONDS")
    user_agent: str = Field(default="api-discovery/0.1", env="USER_AGENT")
    rate_limit_per_second: float = Field(default=5.0, env="RATE_LIMIT_PER_SECOND")


class ServiceNowSettings(CommonSettings):
    base_url: str = Field(env="SERVICENOW_BASE_URL")
    username: Optional[str] = Field(default=None, env="SERVICENOW_USERNAME")
    password: Optional[str] = Field(default=None, env="SERVICENOW_PASSWORD")
    oauth_token: Optional[str] = Field(default=None, env="SERVICENOW_OAUTH_TOKEN")
    allowlist: Optional[str] = Field(default=None, env="SERVICENOW_ALLOWLIST")
    denylist: Optional[str] = Field(default=None, env="SERVICENOW_DENYLIST")


class RunConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_DISCOVERY_", case_sensitive=False, populate_by_name=True)

    state_dir: str = Field(default=".state", env="STATE_DIR")
    specs_dir: str = Field(default="openapi_specs", env="SPECS_DIR")
    logs_dir: str = Field(default="var/log", env="LOGS_DIR")

