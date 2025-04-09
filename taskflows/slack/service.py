from taskflows.service import Calendar, Service


def create_slack_bot_service():
    """Create a systemd service for the Slack bot."""
    return Service(
        name="taskflows-slack-bot",
        description="TaskFlows Slack Bot",
        start_command="tf-slack start",
        start_command_blocking=True,
        restart_policy='on-failure',
    )
