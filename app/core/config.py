from typing import List

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "ePoint CRM API"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = Field(
        default="",
        validation_alias=AliasChoices("FRONTEND_URL", "PORTAL_URL"),
    )

    # Database
    database_url: str
    db_connect_timeout: int = 30
    db_connect_retries: int = 4
    db_connect_retry_delay_seconds: float = 2.0
    db_pool_timeout: int = 60

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7
    password_reset_token_expire_minutes: int = 60

    # Encryption
    encryption_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # S3 / Bucketeer (Heroku inyecta BUCKETEER_* automáticamente)
    aws_access_key_id: str = Field(
        default="",
        validation_alias=AliasChoices("AWS_ACCESS_KEY_ID", "BUCKETEER_AWS_ACCESS_KEY_ID"),
    )
    aws_secret_access_key: str = Field(
        default="",
        validation_alias=AliasChoices("AWS_SECRET_ACCESS_KEY", "BUCKETEER_AWS_SECRET_ACCESS_KEY"),
    )
    aws_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("AWS_REGION", "BUCKETEER_AWS_REGION"),
    )
    s3_bucket_name: str = Field(
        default="",
        validation_alias=AliasChoices("S3_BUCKET_NAME", "BUCKETEER_BUCKET_NAME"),
    )
    s3_endpoint_url: str = ""
    s3_use_ssl: bool = True
    s3_storage_prefix: str = ""

    # Gemini / LangChain
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Notifications
    notifications_dry_run: bool = True
    resend_api_key: str = ""
    sendgrid_api_key: str = ""
    email_from: str = "onboarding@resend.dev"
    email_from_name: str = "ePoint CRM"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    twilio_whatsapp_client_approved_content_sid: str = ""
    whatsapp_default_country_code: str = "54"

    # Recordatorios automáticos de onboarding incompleto (0 = deshabilitado; corre dentro de la API)
    onboarding_reminder_interval_minutes: int = 0

    # Calendly Scheduling API (crear/editar/cancelar). Requiere plan Standard+ en Calendly.
    calendly_write_enabled: bool = False

    # DocuSign eSignature (JWT Grant — credenciales en DB vía UI admin o env opcional)
    docusign_auth_server: str = "account-d.docusign.com"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        # Heroku Postgres usa postgres://; SQLAlchemy/psycopg2 requiere postgresql://
        if isinstance(value, str) and value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql://", 1)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, value: str | List[str]) -> str:
        if isinstance(value, list):
            return ",".join(value)
        return value

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def portal_base_url(self) -> str:
        if self.frontend_url.strip():
            return self.frontend_url.strip().rstrip("/")
        origins = self.cors_origins_list
        if origins:
            return origins[0].rstrip("/")
        return "http://localhost:3000"

    @property
    def portal_login_url(self) -> str:
        return f"{self.portal_base_url}/login"


def get_settings() -> Settings:
    return Settings()
