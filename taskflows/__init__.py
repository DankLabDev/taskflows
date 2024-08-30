from quicklogs import get_logger

logger = get_logger("taskflows")

_SYSTEMD_FILE_PREFIX = "taskflow-"

from alert_msgs import EmailAddrs, SlackChannel

from .tasks import Alerts, task
