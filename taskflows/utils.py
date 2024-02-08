from typing import Literal, Sequence

from alert_msgs import MsgDst
from pydantic import BaseModel
from quicklogs import get_logger

logger = get_logger("taskflows", stdout=True)

_SYSTEMD_FILE_PREFIX = "taskflow_"


class Alerts(BaseModel):
    send_to: Sequence[MsgDst]
    send_on: Sequence[Literal["start", "error", "finish"]]

    def model_post_init(self, __context) -> None:
        if not isinstance(self.send_to, (list, tuple)):
            self.send_to = [self.send_to]
        if isinstance(self.send_on, str):
            self.send_on = [self.send_on]
