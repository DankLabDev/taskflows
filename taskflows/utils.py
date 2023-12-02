import re
from subprocess import run
from typing import Dict, List, Literal, Sequence

from alert_msgs import MsgDst
from pydantic import BaseModel
from quicklogs import get_logger

logger = get_logger("taskflows", stdout=True)

_FILE_PREFIX = "taskflow_"


class Alerts(BaseModel):
    send_to: Sequence[MsgDst]
    send_on: Sequence[Literal["start", "error", "finish"]]

    def model_post_init(self, __context) -> None:
        if not isinstance(self.send_to, (list, tuple)):
            self.send_to = [self.send_to]
        if isinstance(self.send_on, str):
            self.send_on = [self.send_on]


def parse_systemctl_tables(command: List[str]) -> List[Dict[str, str]]:
    res = run(command, capture_output=True)
    lines = res.stdout.decode().split("\n\n")[0].splitlines()
    fields = list(re.finditer(r"[A-Z]+", lines.pop(0)))
    lines_data = []
    for line in lines:
        line_data = {}
        for next_idx, match in enumerate(fields, start=1):
            char_start_idx = match.start()
            if next_idx == len(fields):
                field_text = line[char_start_idx:]
            else:
                field_text = line[char_start_idx : fields[next_idx].start()]
            line_data[match.group()] = field_text.strip()
        lines_data.append(line_data)
    return lines_data
