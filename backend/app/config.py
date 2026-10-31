from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.printer.addresses import AddressPolicy, parse_ports

DEFAULT_SESSION_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://zebra:zebra@localhost:5432/zebra"
    public_url: str = "http://localhost:8000"
    static_dir: Path = Path(__file__).resolve().parent.parent / "static"

    auth_enabled: bool = False
    session_secret: str = DEFAULT_SESSION_SECRET
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_allowed_groups: str = ""

    printer_timeout: float = 5.0
    # Silence (seconds) after which the printer's settings list is considered complete.
    printer_settings_idle: float = 3.0
    # TCP ports printers may use (comma-separated, ranges like 9100-9109): 9100 is the raw ZPL
    # port, 6101 Zebra's alternate one. Keeps the printer endpoints from reaching other services.
    printer_allowed_ports: str = "6101,9100-9109"
    # Allow printers on 127.0.0.1 / ::1, e.g. the emulator during local development.
    printer_allow_loopback: bool = False
    default_printer_name: str = "Zebra ZD420t"
    default_printer_host: str = ""
    default_printer_port: int = 9100
    default_printer_dpi: int = 203

    # Swagger/ReDoc and the OpenAPI spec of the internal (web UI) API at /docs, /redoc and
    # /openapi.json. The external API always documents itself at /api/v1/docs.
    enable_internal_docs: bool = False

    batch_chunk_size: int = 50
    max_upload_bytes: int = 5 * 1024 * 1024
    max_batch_rows: int = 10_000

    @field_validator("printer_allowed_ports")
    @classmethod
    def _check_ports(cls, value: str) -> str:
        parse_ports(value)
        return value

    @model_validator(mode="after")
    def _check_auth(self) -> Settings:
        if self.auth_enabled:
            if (
                self.session_secret in (DEFAULT_SESSION_SECRET, "change-me")
                or len(self.session_secret) < 16
            ):
                raise ValueError("Set SESSION_SECRET to a long random value when AUTH_ENABLED=true")
            if not (self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret):
                raise ValueError(
                    "OIDC_ISSUER, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET are required "
                    "when AUTH_ENABLED=true"
                )
        return self

    @property
    def allowed_groups(self) -> set[str]:
        return {g.strip() for g in self.oidc_allowed_groups.split(",") if g.strip()}

    @property
    def printer_address_policy(self) -> AddressPolicy:
        return AddressPolicy(parse_ports(self.printer_allowed_ports), self.printer_allow_loopback)


@lru_cache
def get_settings() -> Settings:
    return Settings()
