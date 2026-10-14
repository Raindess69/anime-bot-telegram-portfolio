from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(..., alias="BOT_TOKEN")
    db_path: str = Field("bot.db", alias="DB_PATH")
    default_lang: str = Field("ru", alias="DEFAULT_LANG")
    # Optional: register a partner token at https://kodik.cc/. Without it,
    # scheduler simply skips the Kodik source instead of crashing.
    kodik_token: str = Field("", alias="KODIK_TOKEN")
    # Optional: comma-separated proxy pool for Jikan requests (host:port:user:pass,
    # or already-full URLs). Without it, requests go out directly as before.
    jikan_proxies: str = Field("", alias="JIKAN_PROXIES")
    # Mini App settings (accepts either MINI_APP_URL or WEB_APP_URL)
    mini_app_url: str = Field("https://enjoyanime.app", validation_alias=AliasChoices("MINI_APP_URL", "WEB_APP_URL"))
    web_host: str = Field("0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(8080, alias="WEB_PORT")
    dev_mode: bool = Field(False, alias="DEV_MODE")
    # Safe launch flag: disables notification outbox delivery for initial UI-only testing
    disable_outbox_dispatch: bool = Field(False, alias="DISABLE_OUTBOX_DISPATCH")
    # Overall deadline budget for external feed loading in seconds
    feed_timeout_seconds: float = Field(5.0, alias="FEED_TIMEOUT_SECONDS")


def mask_secret(secret: str | None) -> str:
    """Masks secret tokens for safe diagnostic logging."""
    if not secret:
        return "<not set>"
    if len(secret) <= 8:
        return "***"
    return f"{secret[:4]}...{secret[-4:]}"


settings = Settings()
