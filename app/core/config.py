from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_KEY_PATTERNS = ("change-me", "secret", "test", "dev", "local", "example")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="KSeF Backend", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str = Field(alias="DATABASE_URL")
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")
    database_pool_size: int = Field(default=10, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=20, alias="DATABASE_MAX_OVERFLOW")
    contractor_cache_ttl_days: int = Field(default=7, alias="CONTRACTOR_CACHE_TTL_DAYS")

    jwt_secret_key: str | None = Field(default=None, alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    initial_admin_username: str | None = Field(default=None, alias="INITIAL_ADMIN_USERNAME")
    initial_admin_password: str | None = Field(default=None, alias="INITIAL_ADMIN_PASSWORD")

    ksef_environment: str = Field(default="test", alias="KSEF_ENVIRONMENT")
    ksef_auth_token: str | None = Field(default=None, alias="KSEF_AUTH_TOKEN")
    ksef_timeout_seconds: int = Field(default=30, alias="KSEF_TIMEOUT_SECONDS")
    regon_environment: str = Field(default="production", alias="REGON_ENVIRONMENT")
    regon_api_key: str | None = Field(default=None, alias="REGON_API_KEY")
    regon_wsdl_test: str = Field(
        default="https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc?wsdl",
        alias="REGON_WSDL_TEST",
    )
    regon_wsdl_production: str = Field(
        default="https://wyszukiwarkaregon.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc?wsdl",
        alias="REGON_WSDL_PRODUCTION",
    )
    request_timeout_seconds: int = Field(default=15, alias="REQUEST_TIMEOUT_SECONDS")

    seller_nip: str | None = Field(default=None, alias="SELLER_NIP")
    seller_name: str | None = Field(default=None, alias="SELLER_NAME")
    seller_street: str | None = Field(default=None, alias="SELLER_STREET")
    seller_building_no: str | None = Field(default=None, alias="SELLER_BUILDING_NO")
    seller_apartment_no: str | None = Field(default=None, alias="SELLER_APARTMENT_NO")
    seller_postal_code: str | None = Field(default=None, alias="SELLER_POSTAL_CODE")
    seller_city: str | None = Field(default=None, alias="SELLER_CITY")
    seller_country: str = Field(default="PL", alias="SELLER_COUNTRY")

    # Monitoring
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    alert_webhook_url: str | None = Field(default=None, alias="ALERT_WEBHOOK_URL")

    @model_validator(mode="after")
    def _validate_production_security(self) -> "Settings":
        if self.app_env != "production":
            return self

        errors: list[str] = []

        # JWT_SECRET_KEY — musi istnieć, mieć ≥32 znaków i nie być domyślną wartością
        key = self.jwt_secret_key or ""
        if not key:
            errors.append("JWT_SECRET_KEY jest wymagany w trybie production.")
        elif len(key) < 32:
            errors.append(
                f"JWT_SECRET_KEY jest za krótki ({len(key)} znaków); wymagane minimum 32."
            )
        elif any(pat in key.lower() for pat in _INSECURE_KEY_PATTERNS):
            errors.append(
                "JWT_SECRET_KEY zawiera wartość domyślną/testową — zmień na losowy klucz."
            )

        # DEBUG musi być wyłączony na produkcji
        if self.debug:
            errors.append("DEBUG=true jest niedopuszczalne w trybie production.")

        if errors:
            raise ValueError(
                "BLOKADA STARTU — konfiguracja produkcyjna jest niezabezpieczona:\n"
                + "\n".join(f"  \u2022 {e}" for e in errors)
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
