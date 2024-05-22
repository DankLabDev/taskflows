from typing import Literal, Optional, Sequence

from alert_msgs import MsgDst
from pydantic import BaseModel, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict
from quicklogs import get_logger

logger = get_logger("taskflows", stdout=True)

_SYSTEMD_FILE_PREFIX = "taskflow-"


class Config(BaseSettings):
    """S3 configuration. Variables will be loaded from environment variables if set."""

    db_url: Optional[str] = None
    db_schema: str = "taskflows"
    fluent_bit_host: str = "localhost"
    fluent_bit_port: PositiveInt = 24224

    model_config = SettingsConfigDict(env_prefix="taskflows_")


config = Config()


class Alerts(BaseModel):
    send_to: Sequence[MsgDst]
    send_on: Sequence[Literal["start", "error", "finish"]]

    def model_post_init(self, __context) -> None:
        if not isinstance(self.send_to, (list, tuple)):
            self.send_to = [self.send_to]
        if isinstance(self.send_on, str):
            self.send_on = [self.send_on]
