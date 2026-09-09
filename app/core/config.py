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
    app_name: str = "Epoint CRM API"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
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

    # Bootstrap admin (Postman/ops). Vacío = endpoint deshabilitado.
    bootstrap_admin_token: str = Field(
        default="",
        validation_alias=AliasChoices("BOOTSTRAP_ADMIN_TOKEN"),
    )

    # Cuentas de App Store Review: no exigen TOTP ni cambio de contraseña.
    # El resto de clientes sigue con 2FA obligatorio. Lista separada por comas.
    app_review_emails: str = Field(
        default="appreview@epoint.com",
        validation_alias=AliasChoices("APP_REVIEW_EMAILS"),
    )

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

    # Gemini / google-genai
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Direcciones: por defecto se usa Photon (OpenStreetMap), que no requiere credenciales.
    # Definir esta clave solo si se quiere el upgrade a Google Places.
    google_maps_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_MAPS_API_KEY", "GOOGLE_PLACES_API_KEY"),
    )

    # Notifications
    notifications_dry_run: bool = True
    resend_api_key: str = ""
    sendgrid_api_key: str = ""
    email_from: str = "onboarding@resend.dev"
    email_from_name: str = "Epoint Corporation"
    email_reply_to: str = Field(
        default="",
        validation_alias=AliasChoices("EMAIL_REPLY_TO"),
    )
    email_support_url: str = Field(
        default="https://epointsolution.com/",
        validation_alias=AliasChoices("EMAIL_SUPPORT_URL"),
    )
    resend_webhook_secret: str = Field(
        default="",
        validation_alias=AliasChoices("RESEND_WEBHOOK_SECRET"),
    )
    # Local/dev: al abrir el hilo, lee Receiving en Resend (no hace falta túnel).
    # Requiere API key con acceso completo, no "Sending access".
    resend_inbound_sync: bool = Field(
        default=True,
        validation_alias=AliasChoices("RESEND_INBOUND_SYNC"),
    )
    # URL absoluta del logo en emails. Si está vacía, se usa el endpoint público del backend
    # o, en su defecto, {FRONTEND_URL}/epoint-logo.png (debe ser accesible desde internet).
    email_logo_url: str = Field(
        default="",
        validation_alias=AliasChoices("EMAIL_LOGO_URL"),
    )
    # Links de tiendas en el email de bienvenida. Vacío = botón visible sin destino (#).
    android_app_store_url: str = Field(
        default="",
        validation_alias=AliasChoices("ANDROID_APP_STORE_URL", "PLAY_STORE_URL"),
    )
    ios_app_store_url: str = Field(
        default="",
        validation_alias=AliasChoices("IOS_APP_STORE_URL", "APP_STORE_URL"),
    )
    # En sandbox de Resend, redirige todos los emails a esta dirección verificada.
    email_dev_redirect_to: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    twilio_whatsapp_client_approved_content_sid: str = ""
    whatsapp_default_country_code: str = "54"

    # Recordatorios automáticos de onboarding incompleto (0 = deshabilitado; corre dentro de la API)
    onboarding_reminder_interval_minutes: int = 0
    # No reenviar recordatorio de onboarding incompleto antes de N horas
    onboarding_reminder_cooldown_hours: int = 24
    # No reenviar recordatorio de saldo de pago antes de N horas
    payment_reminder_cooldown_hours: int = 24
    # No reenviar recordatorio de firma de contrato antes de N horas
    contract_reminder_cooldown_hours: int = 24
    # No reenviar recordatorio de tareas del tablero antes de N horas
    board_reminder_cooldown_hours: int = 24

    # Calendly Scheduling API (crear/editar/cancelar). Requiere plan Standard+ en Calendly.
    calendly_write_enabled: bool = False

    # DocuSign eSignature (JWT Grant — cuenta única de empresa vía variables de entorno)
    docusign_integration_key: str = ""
    docusign_user_id: str = ""
    docusign_account_id: str = ""
    docusign_private_key: str = ""
    docusign_auth_server: str = "account-d.docusign.com"
    docusign_base_uri: str = ""
    docusign_default_template_id: str = ""
    docusign_default_template_role_name: str = "Cliente"
    docusign_connect_hmac_key: str = ""
    backend_public_url: str = Field(
        default="",
        validation_alias=AliasChoices("BACKEND_PUBLIC_URL", "API_PUBLIC_URL"),
    )

    # Pagos — general
    payments_enabled: bool = True
    payments_default_provider: str = "authorize"
    # Si True, los links públicos muestran "Pagar" y aprueban sin cobro real.
    payment_test: bool = False

    # Pagos — Stripe (legacy, no expuesto en UI)
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""

    # Pagos — Authorize.net
    authorize_api_login_id: str = ""
    authorize_transaction_key: str = ""
    authorize_signature_key: str = ""
    authorize_environment: str = Field(
        default="sandbox",
        validation_alias=AliasChoices("AUTHORIZE_ENV", "AUTHORIZE_ENVIRONMENT"),
    )

    # Pagos — PayPal
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_environment: str = Field(
        default="sandbox",
        validation_alias=AliasChoices("PAYPAL_ENV", "PAYPAL_ENVIRONMENT"),
    )

    @field_validator("docusign_private_key", mode="after")
    @classmethod
    def normalize_docusign_private_key(cls, value: str) -> str:
        if value and "\\n" in value:
            return value.replace("\\n", "\n")
        return value

    @property
    def docusign_configured(self) -> bool:
        return bool(
            self.docusign_integration_key.strip()
            and self.docusign_user_id.strip()
            and self.docusign_account_id.strip()
            and self.docusign_private_key.strip()
            and self.docusign_base_uri.strip()
        )

    @property
    def google_maps_configured(self) -> bool:
        return bool(self.google_maps_api_key.strip())

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key.strip() and self.stripe_publishable_key.strip())

    @property
    def authorize_configured(self) -> bool:
        return bool(self.authorize_api_login_id.strip() and self.authorize_transaction_key.strip())

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id.strip() and self.paypal_client_secret.strip())

    @property
    def authorize_environment_normalized(self) -> str:
        env = self.authorize_environment.strip().lower()
        return "production" if env in {"production", "prod", "live"} else "sandbox"

    @property
    def paypal_environment_normalized(self) -> str:
        env = self.paypal_environment.strip().lower()
        return "production" if env in {"production", "prod", "live"} else "sandbox"

    @property
    def payments_default_provider_normalized(self) -> str:
        provider = self.payments_default_provider.strip().lower()
        if provider in ("authorize", "paypal"):
            return provider
        return "authorize"

    @property
    def payments_webhook_base_url(self) -> str | None:
        base = (self.backend_public_url or "").strip().rstrip("/")
        if not base:
            return None
        return f"{base}{self.api_prefix}/payments/webhooks"

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
    def cors_allow_origin_regex(self) -> str | None:
        """En local, Next también sirve 127.0.0.1 y la IP de LAN/Tailscale."""
        if not self.is_development:
            return None
        return (
            r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
            r"|https?://\[::1\]:\d+"
            r"|https?://(10|100|192\.168)\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+"
        )

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

    @property
    def portal_board_url(self) -> str:
        return f"{self.portal_base_url}/portal/tablero"

    @property
    def docusign_webhook_url(self) -> str | None:
        base = self.backend_public_url.strip().rstrip("/")
        if not base:
            return None
        prefix = self.api_prefix if self.api_prefix.startswith("/") else f"/{self.api_prefix}"
        return f"{base}{prefix}/docusign/webhook"


def get_settings() -> Settings:
    return Settings()
