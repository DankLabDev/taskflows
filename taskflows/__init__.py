from quicklogs import get_logger

logger = get_logger("taskflows", terminal=True)

_SYSTEMD_FILE_PREFIX = "taskflow-"

from alert_msgs import Email, Slack

from .tasks import Alerts, task
