import io
import re
import sys
from contextlib import redirect_stderr, redirect_stdout

from slack_bolt import Ack, App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from taskflows import logger
from taskflows.admin import cli as admin_cli

from .config import config

# Initialize the Slack app
app = App(
    token=config.bot_token,
    signing_secret=config.signing_secret
)


def is_authorized(user_id: str, channel_id: str) -> bool:
    """Check if the user is authorized to use this bot."""
    if config.allowed_users and user_id not in config.allowed_users:
        logger.warning(f"Unauthorized user {user_id} attempted to use the bot")
        return False
    
    if config.allowed_channels and channel_id not in config.allowed_channels:
        logger.warning(f"Unauthorized channel {channel_id} attempted to use the bot")
        return False
        
    return True


def format_for_slack(text: str) -> str:
    """Format the output for Slack."""
    # Strip ANSI color codes
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    return f"```\n{text}\n```" if text else "Command executed successfully."


def run_command(command_string: str) -> str:
    """Run a taskflows CLI command and return the output."""
    # Split the command string into args
    args = command_string.strip().split()
    
    # Capture stdout and stderr
    output_buffer = io.StringIO()
    error_buffer = io.StringIO()
    
    try:
        with redirect_stdout(output_buffer), redirect_stderr(error_buffer):
            # Call the Click CLI with the provided arguments
            admin_cli.main(args=args, standalone_mode=False)
    except SystemExit as e:
        # Catch the SystemExit that Click raises
        if e.code != 0:
            return f"Error: {error_buffer.getvalue() or 'Command failed with exit code ' + str(e.code)}"
    except Exception as e:
        logger.exception(f"Error executing command: {command_string}")
        return f"Error: {str(e)}"
    
    return output_buffer.getvalue() or "Command executed successfully."


@app.command("/tf")
def handle_tf_command(ack: Ack, command, client):
    """Handle /tf slash command."""
    ack()
    user_id = command["user_id"]
    channel_id = command["channel_id"]
    
    if not is_authorized(user_id, channel_id):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="You are not authorized to use this command."
        )
        return
    
    command_text = command["text"]
    if not command_text:
        client.chat_postMessage(
            channel=channel_id,
            text="Please provide a command. Available commands: history, list, status, logs, create, start, stop, restart, enable, disable, remove, show"
        )
        return
    
    # Start a thinking message
    response = client.chat_postMessage(
        channel=channel_id,
        text=f"Running command: `tf {command_text}`..."
    )
    
    # Run the command
    result = run_command(command_text)
    
    # Update the message with the result
    try:
        client.chat_update(
            channel=channel_id,
            ts=response["ts"],
            text=f"Command: `tf {command_text}`\n\n{format_for_slack(result)}"
        )
    except SlackApiError as e:
        logger.error(f"Error updating message: {e}")
        client.chat_postMessage(
            channel=channel_id,
            text=f"Command: `tf {command_text}`\n\n{format_for_slack(result)}"
        )


@app.event("app_mention")
def handle_app_mention(event, say, client):
    """Handle mentions of the bot."""
    user_id = event["user"]
    channel_id = event["channel"]
    
    if not is_authorized(user_id, channel_id):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="You are not authorized to use this bot."
        )
        return
    
    text = event["text"]
    # Extract command: remove the app mention
    command_text = re.sub(r'<@[A-Z0-9]+>', '', text).strip()
    
    if not command_text:
        say("How can I help you? Try `@TaskFlows status` or other commands.")
        return
    
    # Post a thinking message
    response = say(f"Running command: `tf {command_text}`...")
    
    # Run the command
    result = run_command(command_text)
    
    # Update the message with the result
    try:
        client.chat_update(
            channel=channel_id,
            ts=response["ts"],
            text=f"Command: `tf {command_text}`\n\n{format_for_slack(result)}"
        )
    except SlackApiError as e:
        logger.error(f"Error updating message: {e}")
        say(f"Command: `tf {command_text}`\n\n{format_for_slack(result)}")


def start_bot():
    """Start the Slack bot."""
    logger.info("Starting TaskFlows Slack bot...")
    
    if config.use_socket_mode:
        if not config.app_token:
            logger.error("Socket mode requires an app token")
            sys.exit(1)
        handler = SocketModeHandler(app, config.app_token)
        handler.start()
    else:
        app.start(port=3000)
