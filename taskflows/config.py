from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """S3 configuration. Variables will be loaded from environment variables if set."""

    db_url: Optional[str] = None
    db_schema: str = "taskflows"
    display_timezone: str = "UTC"
    docker_log_driver: Optional[
        Literal["journald", "fluentd", "syslog", "journald", "gelf", "none"]
    ] = "fluentd"

    model_config = SettingsConfigDict(env_prefix="taskflows_")


config = Config()
