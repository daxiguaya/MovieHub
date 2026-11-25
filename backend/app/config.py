"""Environment-backed application settings."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOVIEHUB_",
        case_sensitive=False,
        extra="ignore",
    )

    data_dir: Path = Path("/data")
    backup_dir: Path = Path("/backups")
    import_dir: Path = Path("/imports")
    api_key: str = ""
    xiaoya_search_url_template: str = ""
    cors_origins: list[str] = Field(default_factory=list)
    # TMDB's read access token is intentionally unprefixed to match the
    # existing NAS/GitHub secret name and is never exposed to the browser.
    tmdb_api_read_token: str = Field(
        default="",
        validation_alias="TMDB_API_READ_TOKEN",
        repr=False,
    )

    rate_limit_search: str = "120/minute"
    rate_limit_genres: str = "60/minute"
    rate_limit_regions: str = "60/minute"
    rate_limit_stats: str = "60/minute"
    rate_limit_poster: str = "60/minute"
    rate_limit_import: str = "5/minute"


settings = Settings()
