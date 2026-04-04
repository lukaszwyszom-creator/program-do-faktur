from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
