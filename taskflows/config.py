from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel, PositiveInt

taskflows_data_dir = Path.home() / ".taskflows"
taskflows_data_dir.mkdir(parents=True, exist_ok=True)


class Config(BaseSettings):
    """S3 configuration. Variables will be loaded from environment variables if set."""

    db_url: Optional[str] = None
    db_schema: str = "taskflows"
    display_timezone: str = "UTC"
    fluent_bit: str = "0.0.0.0:24224"
    grafana: str = "0.0.0.0:3000"
    grafana_api_key: Optional[str] = None

    model_config = SettingsConfigDict(env_prefix="taskflows_")

config = Config()
