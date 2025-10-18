"""Configuration loading for Tiny Email App (TEA)."""

from __future__ import annotations

from functools import lru_cache
from types import MethodType
from typing import List, Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class TeaSettings(BaseSettings):
    """Application configuration sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="TEA_",
        env_file=".env",
        extra="allow",
    )

    app_host: str = Field(default="0.0.0.0", description="Host for the FastAPI server.")
    app_port: int = Field(default=8000, description="Port for the FastAPI server.")
    debug: bool = Field(default=False, description="Enable verbose logging.")
    dry_run: bool = Field(default=False, description="Skip outbound email delivery when enabled.")

    novnc_enabled: bool = Field(default=True, description="Expose the embedded noVNC server.")
    novnc_password_enabled: bool = Field(default=False, description="Require password for noVNC access.")
    novnc_password: Optional[str] = Field(default=None, description="Password protecting the noVNC server when enabled.")
    novnc_display: str = Field(default=":0", description="X display identifier for the virtual desktop.")
    novnc_geometry: str = Field(default="1280x800x24", description="Virtual desktop geometry for Xvfb.")
    novnc_vnc_port: int = Field(default=5900, description="Internal VNC server port.")
    novnc_web_port: int = Field(
        default=6080,
        description="noVNC websocket port exposed to clients.",
        validation_alias=AliasChoices("NOVNC_PORT", "TEA_NOVNC_WEB_PORT"),
    )

    relay_send_enabled: bool = Field(default=True, description="Allow unauthenticated email relay submission.")
    relay_query_enabled: bool = Field(default=False, description="Allow unauthenticated inbox querying.")

    mock_mode: bool = Field(default=False, description="Use mock implementations for transports and providers.")

    secret_store_path: Optional[str] = Field(default=None, description="Path to an optional secret store mounted as a file.")

    oauth_client_id: Optional[str] = Field(default=None, description="OAuth client identifier.")
    oauth_client_secret: Optional[str] = Field(default=None, description="OAuth client secret.")
    oauth_tenant: Optional[str] = Field(default=None, description="Tenant or domain for the OAuth provider.")
    oauth_scopes: List[str] = Field(default_factory=list, description="Scopes requested for OAuth tokens.")
    oauth_auth_endpoint: Optional[str] = Field(default=None, description="Authorization endpoint for OAuth flows.")
    oauth_token_endpoint: Optional[str] = Field(default=None, description="Token endpoint for OAuth flows.")
    oauth_redirect_uri: Optional[str] = Field(default=None, description="Redirect URI registered with the provider.")
    oauth_refresh_token: Optional[str] = Field(default=None, description="Stored refresh token for long-lived sessions.")
    oauth_access_token: Optional[str] = Field(default=None, description="Bootstrap access token if already obtained.")

    smtp_host: Optional[str] = Field(default=None, description="SMTP server hostname.")
    smtp_port: int = Field(default=587, description="SMTP server port.")
    smtp_use_tls: bool = Field(default=True, description="Use TLS/STARTTLS for SMTP connections.")

    imap_host: Optional[str] = Field(default=None, description="IMAP server hostname.")
    imap_port: int = Field(default=993, description="IMAP server port.")
    imap_use_ssl: bool = Field(default=True, description="Use SSL/TLS for IMAP connections.")

    health_status_cache_ttl: int = Field(default=30, description="Seconds to cache expensive health checks.")

    @property
    def noVNC_password_required(self) -> bool:
        return self.novnc_enabled and self.novnc_password_enabled and bool(self.novnc_password)

    @field_validator("oauth_scopes", mode="before")
    @classmethod
    def _split_scopes(cls, value: object) -> List[str]:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            return [scope for scope in value.replace(",", " ").split() if scope]
        if value is None:
            return []
        return list(value)

    @staticmethod
    def _install_blank_guard(source):
        original_decode = source.decode_complex_value

        def decode(self, field_name, field, value):
            if isinstance(value, str) and not value.strip():
                return value
            return original_decode(field_name, field, value)

        source.decode_complex_value = MethodType(decode, source)
        return source

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Use env sources that tolerate blank complex values."""

        return (
            init_settings,
            cls._install_blank_guard(env_settings),
            cls._install_blank_guard(dotenv_settings),
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def get_settings() -> TeaSettings:
    """Return cached settings instance."""

    return TeaSettings()
