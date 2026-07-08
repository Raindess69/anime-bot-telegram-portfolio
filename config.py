from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(..., alias="BOT_TOKEN")
    db_path: str = Field("bot.db", alias="DB_PATH")
    default_lang: str = Field("ru", alias="DEFAULT_LANG")
    # Optional: register a partner token at https://kodik.cc/. Without it,
    # scheduler simply skips the Kodik source instead of crashing.
    kodik_token: str = Field("", alias="KODIK_TOKEN")


settings = Settings()
