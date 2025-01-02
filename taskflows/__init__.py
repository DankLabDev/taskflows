from quicklogs import get_logger

logger = get_logger("taskflows")

_SYSTEMD_FILE_PREFIX = "taskflow-"

from alert_msgs import EmailAddrs, SlackChannel

from .common import (
    HTTPClient,
    HTTPResponse,
    ShutdownHandler,
    get_http_client,
    get_shutdown_handler,
)
from .tasks import Alerts, task
