"""Environment-backed application settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOVIEHUB_",
        case_sensitive=False,
        extra="ignore",
    )

    data_dir: Path = Path("/data")
    import_dir: Path = Path("/imports")
    api_key: str = ""

    rate_limit_search: str = "120/minute"
    rate_limit_genres: str = "60/minute"
    rate_limit_regions: str = "60/minute"
    rate_limit_stats: str = "60/minute"
    rate_limit_poster: str = "60/minute"
    rate_limit_import: str = "5/minute"


settings = Settings()
