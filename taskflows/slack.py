import io
import re
import sys
import time
import asyncio
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import click

from taskflows import logger  # noqa: F401 (keep single import)

from slack_bolt import Ack, App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from taskflows import logger
from taskflows.cli import cli as admin_cli

from pydantic_settings import BaseSettings, SettingsConfigDict


class SlackConfig(BaseSettings):
    """Slack app configuration settings."""
    bot_token: str
    signing_secret: str
    app_token: str = ""  # For socket mode, optional
    allowed_users: list[str] = []  # Slack user IDs who can use the bot
    allowed_channels: list[str] = []  # Channel IDs where the bot can be used
    use_socket_mode: bool = False  # Use Socket Mode instead of HTTP
    rate_limit_per_minute: int = 10  # Rate limit per user per minute
    dangerous_commands: list[str] = ["remove", "stop", "disable"]  # Commands requiring confirmation
    
    model_config = SettingsConfigDict(env_prefix="taskflows_slack_")


config = SlackConfig()

# Rate limiting storage (in production, use Redis or similar)
user_rate_limits: Dict[str, List[float]] = {}

# User context storage
user_contexts: Dict[str, Dict] = {}

# Initialize the Slack app
app = App(
    token=config.bot_token,
    signing_secret=config.signing_secret
)


def is_authorized(user_id: str, channel_id: str) -> bool:
    """Check if the user is authorized to use this bot."""
    if config.allowed_users and user_id not in config.allowed_users:
        return False
    if config.allowed_channels and channel_id not in config.allowed_channels:
        return False
    return True


def check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit."""
    now = time.time()
    minute_ago = now - 60
    
    if user_id not in user_rate_limits:
        user_rate_limits[user_id] = []
    
    # Remove old entries
    user_rate_limits[user_id] = [t for t in user_rate_limits[user_id] if t > minute_ago]
    
    # Check limit
    if len(user_rate_limits[user_id]) >= config.rate_limit_per_minute:
        return False
    
    # Add current request
    user_rate_limits[user_id].append(now)
    return True


def get_user_context(user_id: str) -> Dict:
    """Get or create user context."""
    if user_id not in user_contexts:
        user_contexts[user_id] = {
            "last_commands": [],
            "preferences": {},
            "pending_confirmations": {}
        }
    return user_contexts[user_id]


def add_to_command_history(user_id: str, command: str):
    """Add command to user's history."""
    context = get_user_context(user_id)
    context["last_commands"].insert(0, command)
    context["last_commands"] = context["last_commands"][:10]  # Keep last 10


def format_for_slack(text: str, command: str = "") -> str:
    """Format the output for Slack with better styling."""
    # Strip ANSI color codes
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    
    if not text:
        return "✅ Command executed successfully."
    
    # Add emoji based on command type
    emoji = get_command_emoji(command)
    
    # Format as code block with proper spacing
    if len(text) > 2000:  # Slack message limit consideration
        text = text[:1900] + "...\n[Output truncated]"
    
    return f"{emoji} ```\n{text}\n```"


def get_command_emoji(command: str) -> str:
    """Get appropriate emoji for command."""
    emoji_map = {
        "status": "📊",
        "list": "📋",
        "history": "📜",
        "logs": "📄",
        "start": "▶️",
        "stop": "⏹️",
        "restart": "🔄",
        "create": "🆕",
        "remove": "🗑️",
        "enable": "✅",
        "disable": "❌",
        "show": "👁️",
    }
    
    for cmd, emoji in emoji_map.items():
        if cmd in command.lower():
            return emoji
    
    return "🤖"


def get_help_text() -> str:
    """Get comprehensive help text."""
    return """🤖 *TaskFlows Bot Commands*

*Dashboard Options:*
• `🏠 App Home` - Click TaskFlows app in sidebar (Recommended)
• `/tf-dashboard` - Channel dashboard with buttons
• `/tf-dashboard modal` - Pop-up modal dashboard
• `/tf-dashboard web` - Link to external web dashboard

*Basic Commands:*
• `status` - Show service status
• `list` - List all services
• `history` - Show task run history
• `logs <service>` - Show service logs

*Service Management:*
• `start <service>` - Start a service
• `stop <service>` - Stop a service  
• `restart <service>` - Restart a service
• `enable <service>` - Enable a service
• `disable <service>` - Disable a service

*Advanced:*
• `create <file>` - Create services from file
• `remove <service>` - Remove a service (requires confirmation)
• `show <service>` - Show service details

*Shortcuts:*
• `st` → `status`
• `ls` → `list`
• `h` → `history`
• `d` → `dashboard`

*Examples:*
• `/tf status` - Show all service status
• `/tf start my-service` - Start specific service
• `/tf logs my-service` - View service logs
• `/tf-dashboard modal` - Open modal dashboard

💡 *Tips:*
• Use App Home for the best experience
• Use `status --running` to see only active services
• Use `history --limit 10` to see more history
• Add `--match pattern` to filter results
• Dangerous commands require confirmation for safety
• Rate limited to prevent abuse"""


def validate_command(command: str) -> tuple[bool, str]:
    """Validate command syntax and arguments."""
    if not command.strip():
        return False, "❌ Empty command. Use `help` to see available commands."
    
    parts = command.strip().split()
    base_cmd = parts[0]
    
    # Map shortcuts
    shortcuts = {
        "st": "status",
        "ls": "list", 
        "h": "history",
        "r": "restart",
        "s": "start"
    }
    
    if base_cmd in shortcuts:
        parts[0] = shortcuts[base_cmd]
        command = " ".join(parts)
    
    # Check for dangerous commands
    if base_cmd in config.dangerous_commands and len(parts) < 2:
        return False, f"❌ Command `{base_cmd}` requires a service name for safety."
    
    return True, command


def run_command(command_string: str, user_id: str = "") -> str:
    """Run a taskflows CLI command and return the output."""
    # Validate command first
    is_valid, result = validate_command(command_string)
    if not is_valid:
        return result
    
    command_string = result  # Use validated/transformed command
    
    # Add to user history
    if user_id:
        add_to_command_history(user_id, command_string)
    
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
            error_msg = error_buffer.getvalue()
            if not error_msg:
                error_msg = f"Command failed with exit code {e.code}"
            return f"❌ Error: {error_msg}"
    except Exception as e:
        logger.exception(f"Error executing command: {command_string}")
        return f"❌ Error: {str(e)}"
    
    output = output_buffer.getvalue()
    error = error_buffer.getvalue()
    
    if error:
        return f"⚠️ Warning: {error}\n\n{output}" if output else f"❌ Error: {error}"
    
    return output or "✅ Command executed successfully."


def requires_confirmation(command: str, user_id: str) -> tuple[bool, str]:
    """Check if command requires confirmation."""
    parts = command.strip().split()
    if not parts:
        return False, ""
    
    base_cmd = parts[0]
    if base_cmd in config.dangerous_commands:
        context = get_user_context(user_id)
        confirmation_key = f"{base_cmd}_{command}"
        
        # Check if already confirmed
        if confirmation_key in context["pending_confirmations"]:
            confirm_time = context["pending_confirmations"][confirmation_key]
            if time.time() - confirm_time < 300:  # 5 minutes
                del context["pending_confirmations"][confirmation_key]
                return False, ""
        
        # Store pending confirmation
        context["pending_confirmations"][confirmation_key] = time.time()
        
        return True, f"⚠️ *Dangerous Command Warning*\n\nYou're about to run: `{command}`\n\n" \
                     f"This command could affect running services. Please confirm by running the same command again within 5 minutes."
    
    return False, ""


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
            text="❌ You are not authorized to use this command."
        )
        return
    
    if not check_rate_limit(user_id):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⏰ Rate limit exceeded. Please wait a minute before sending more commands."
        )
        return
    
    command_text = command["text"].strip()
    if not command_text:
        dashboard = create_status_dashboard(command["user_id"])
        client.chat_postMessage(
            channel=channel_id,
            text=get_help_text(),
            **dashboard
        )
        return
    
    # Handle help command
    if command_text.lower() in ["help", "h", "?"]:
        dashboard = create_status_dashboard(user_id)
        client.chat_postMessage(
            channel=channel_id,
            text=get_help_text(),
            **dashboard
        )
        return
    
    # Handle dashboard command
    if command_text.lower() in ["dashboard", "dash", "d"]:
        dashboard = create_status_dashboard(user_id)
        client.chat_postMessage(
            channel=channel_id,
            text="🤖 *TaskFlows Interactive Dashboard*",
            **dashboard
        )
        return
    
    # Check if command requires confirmation
    needs_confirmation, confirmation_msg = requires_confirmation(command_text, user_id)
    if needs_confirmation:
        client.chat_postMessage(
            channel=channel_id,
            text=confirmation_msg
        )
        return
    
    # Start a thinking message with emoji
    emoji = get_command_emoji(command_text)
    response = client.chat_postMessage(
        channel=channel_id,
        text=f"{emoji} Running command: `tf {command_text}`..."
    )
    
    # Run the command
    result = run_command(command_text, user_id)
    
    # Update the message with the result
    try:
        client.chat_update(
            channel=channel_id,
            ts=response["ts"],
            text=f"*Command:* `tf {command_text}`\n\n{format_for_slack(result, command_text)}"
        )
    except SlackApiError as e:
        logger.error(f"Error updating message: {e}")
        client.chat_postMessage(
            channel=channel_id,
            text=f"*Command:* `tf {command_text}`\n\n{format_for_slack(result, command_text)}"
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
            text="❌ You are not authorized to use this bot."
        )
        return
    
    if not check_rate_limit(user_id):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⏰ Rate limit exceeded. Please wait a minute before sending more commands."
        )
        return
    
    text = event["text"]
    # Extract command: remove the app mention
    command_text = re.sub(r'<@[A-Z0-9]+>', '', text).strip()
    
    if not command_text or command_text.lower() in ["help", "h", "?"]:
        dashboard = create_status_dashboard(user_id)
        say(get_help_text(), **dashboard)
        return
    
    # Handle dashboard command
    if command_text.lower() in ["dashboard", "dash", "d"]:
        dashboard = create_status_dashboard(user_id)
        say("🤖 *TaskFlows Interactive Dashboard*", **dashboard)
        return
    
    # Check for quick status requests
    if command_text.lower() in ["status", "st"]:
        command_text = "status"
    elif command_text.lower() in ["list", "ls"]:
        command_text = "list"
    elif command_text.lower() in ["history", "h"]:
        command_text = "history"
    
    # Check if command requires confirmation
    needs_confirmation, confirmation_msg = requires_confirmation(command_text, user_id)
    if needs_confirmation:
        say(confirmation_msg)
        return
    
    # Post a thinking message with proper emoji
    emoji = get_command_emoji(command_text)
    response = say(f"{emoji} Running command: `tf {command_text}`...")
    
    # Run the command
    result = run_command(command_text, user_id)
    
    # Update the message with the result
    try:
        client.chat_update(
            channel=channel_id,
            ts=response["ts"],
            text=f"*Command:* `tf {command_text}`\n\n{format_for_slack(result, command_text)}"
        )
    except SlackApiError as e:
        logger.error(f"Error updating message: {e}")
        say(f"*Command:* `tf {command_text}`\n\n{format_for_slack(result, command_text)}")


@app.action("quick_status")
def handle_quick_status(ack, body, client):
    """Handle quick status button press."""
    ack()
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    
    if not is_authorized(user_id, channel_id) or not check_rate_limit(user_id):
        return
    
    result = run_command("status", user_id)
    
    client.chat_postMessage(
        channel=channel_id,
        text=f"*Quick Status Check*\n\n{format_for_slack(result, 'status')}"
    )


@app.action("quick_list")
def handle_quick_list(ack, body, client):
    """Handle quick list button press."""
    ack()
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    
    if not is_authorized(user_id, channel_id) or not check_rate_limit(user_id):
        return
    
    result = run_command("list", user_id)
    
    client.chat_postMessage(
        channel=channel_id,
        text=f"*Service List*\n\n{format_for_slack(result, 'list')}"
    )


@app.shortcut("taskflows_quick_actions")
def handle_shortcut(ack, shortcut, client):
    """Handle global shortcut for quick actions."""
    ack()
    
    user_id = shortcut["user"]["id"]
    
    if not check_rate_limit(user_id):
        return
    
    # Open a modal with quick actions
    client.views_open(
        trigger_id=shortcut["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "quick_actions_modal",
            "title": {"type": "plain_text", "text": "TaskFlows Quick Actions"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Choose a quick action:"}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📊 Status"},
                            "action_id": "quick_status",
                            "style": "primary"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📋 List Services"},
                            "action_id": "quick_list"
                        }
                    ]
                },
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Recent Commands:*"}
                }
            ]
        }
    )


def create_status_dashboard(user_id: Optional[str] = None) -> dict:
    """Create an interactive status dashboard."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🤖 TaskFlows Dashboard"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Quick actions for TaskFlows management:"}
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📊 Status"},
                    "action_id": "quick_status",
                    "style": "primary"
                },
                {
                    "type": "button", 
                    "text": {"type": "plain_text", "text": "📋 List"},
                    "action_id": "quick_list"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📜 History"},
                    "action_id": "quick_history"
                }
            ]
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "💡 *Tip:* Use `/tf help` for full command reference"}
        }
    ]
    
    # Include recent command suggestions for channel dashboard
    if user_id:
        suggestions = format_command_suggestions(user_id)
        if suggestions:
            blocks.append({"type": "divider"})
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": suggestions}})
    
    return {"blocks": blocks}


@app.action("quick_history")
def handle_quick_history(ack, body, client):
    """Handle quick history button press."""
    ack()
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    
    if not is_authorized(user_id, channel_id) or not check_rate_limit(user_id):
        return
    
    result = run_command("history", user_id)
    
    client.chat_postMessage(
        channel=channel_id,
        text=f"*Task History*\n\n{format_for_slack(result, 'history')}"
    )


@app.command("/tf-health")
def handle_health_check(ack: Ack, command, client):
    """Handle health check command."""
    ack()
    user_id = command["user_id"]
    channel_id = command["channel_id"]
    
    if not is_authorized(user_id, channel_id):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="❌ You are not authorized to use this command."
        )
        return
    
    # Quick health check
    try:
        # Test database connection
        from taskflows.db import engine
        with engine.begin() as conn:
            conn.execute("SELECT 1")
        
        db_status = "✅ Connected"
    except Exception as e:
        db_status = f"❌ Error: {str(e)[:100]}"
    
    # Check systemd connection
    try:
        from taskflows.service.service import systemd_manager
        manager = systemd_manager()
        systemd_status = "✅ Connected"
    except Exception as e:
        systemd_status = f"❌ Error: {str(e)[:100]}"
    
    uptime = time.time() - start_time if 'start_time' in globals() else 0
    
    health_report = f"""🏥 *TaskFlows Bot Health Check*

• *Database:* {db_status}
• *SystemD:* {systemd_status}
• *Bot Uptime:* {uptime:.1f} seconds
• *Active Users:* {len(user_contexts)}
• *Rate Limits:* {len(user_rate_limits)} users tracked

✅ Bot is operational!"""
    
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=health_report
    )


# Track bot start time
start_time = time.time()

def start_bot():
    """Start the Slack bot."""
    logger.info("Starting TaskFlows Slack bot...")
    
    # Start cleanup task
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(periodic_cleanup())
    except RuntimeError:
        # If no loop exists, create one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(periodic_cleanup())
    
    if config.use_socket_mode:
        if not config.app_token:
            logger.error("Socket mode requires an app token")
            sys.exit(1)
        handler = SocketModeHandler(app, config.app_token)
        handler.start()
    else:
        app.start(port=3000)

@click.group()
def cli():
    """TaskFlows Slack bot CLI."""
    pass


@cli.command()
@click.option("--debug", is_flag=True, help="Enable debug mode")
def start(debug):
    """Start the TaskFlows Slack bot."""
    if debug:
        logger.setLevel("DEBUG")
    start_bot()


@cli.command()
def install():
    """Setup instructions for installing the Slack app."""
    click.echo("""
TaskFlows Slack Bot Installation

1. Go to https://api.slack.com/apps and create a new app
2. Under "OAuth & Permissions", add these scopes:
   - chat:write
   - commands
   - app_mentions:read
   - im:read
   - channels:read
   - groups:read
3. Under "App Home":
   - Enable App Home
   - Enable "Allow users to send Slash commands and messages from the messages tab"
4. Under "Interactivity & Shortcuts":
   - Enable Interactivity
   - Set Request URL to your bot's URL + /slack/events
   - Add Global Shortcut:
     - Name: TaskFlows Quick Actions
     - Callback ID: taskflows_quick_actions
5. Create slash commands:
   - "/tf" with the URL to your bot
   - "/tf-dashboard" for dashboard options
   - "/tf-health" for health checks
6. Install the app to your workspace
7. Set these environment variables:
   - TASKFLOWS_SLACK_BOT_TOKEN=xoxb-your-token
   - TASKFLOWS_SLACK_SIGNING_SECRET=your-signing-secret
   - TASKFLOWS_SLACK_ALLOWED_USERS=U12345,U67890 (optional)
   - TASKFLOWS_SLACK_ALLOWED_CHANNELS=C12345,C67890 (optional)
   - TASKFLOWS_SLACK_USE_SOCKET_MODE=true (optional)
   - TASKFLOWS_SLACK_APP_TOKEN=xapp-your-token (required if using socket mode)
   - TASKFLOWS_SLACK_RATE_LIMIT_PER_MINUTE=10 (optional, default: 10)
   - TASKFLOWS_SLACK_DANGEROUS_COMMANDS=remove,stop,disable (optional)
8. Run "tf-slack start" to start the bot

🎛️ Dashboard Options:
📱 App Home Dashboard - Click the app in your sidebar (Recommended)
💬 Channel Dashboard - Use `/tf dashboard` or `/tf-dashboard`
🖥️ Modal Dashboard - Use `/tf-dashboard modal`
🌐 Web Integration - Use `/tf-dashboard web`

✨ New Features:
🏠 Dedicated App Home with real-time status
🎯 Interactive service management modals
⚡ Command shortcuts (st=status, ls=list, h=history)
🛡️ Rate limiting and dangerous command confirmation
📊 Enhanced formatting with emojis
🔍 Comprehensive help system
📈 User command history tracking
⚙️ Service start/stop/logs via GUI
🔄 Auto-refreshing dashboard
""")


def cleanup_old_confirmations():
    """Clean up old pending confirmations."""
    current_time = time.time()
    for user_id, context in user_contexts.items():
        expired_keys = [
            key for key, timestamp in context["pending_confirmations"].items()
            if current_time - timestamp > 300  # 5 minutes
        ]
        for key in expired_keys:
            del context["pending_confirmations"][key]


def get_recent_commands(user_id: str, limit: int = 5) -> list:
    """Get user's recent commands."""
    context = get_user_context(user_id)
    return context["last_commands"][:limit]


def format_command_suggestions(user_id: str) -> str:
    """Format recent commands as suggestions."""
    recent = get_recent_commands(user_id)
    if not recent:
        return ""
    
    suggestions = "\n".join([f"• `{cmd}`" for cmd in recent[:3]])
    return f"\n\n*Recent commands:*\n{suggestions}"


@app.error
def error_handler(error, body, logger):
    """Global error handler for the Slack app."""
    logger.exception(f"Error handling Slack event: {error}")
    return "❌ Something went wrong. Please try again later."


# Periodic cleanup task
async def periodic_cleanup():
    """Periodically clean up old data."""
    while True:
        try:
            cleanup_old_confirmations()
            current_time = time.time()
            minute_ago = current_time - 60
            for user_id in list(user_rate_limits.keys()):
                user_rate_limits[user_id] = [
                    t for t in user_rate_limits[user_id] if t > minute_ago
                ]
                if not user_rate_limits[user_id]:
                    del user_rate_limits[user_id]
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")
            await asyncio.sleep(60)

def create_app_home_dashboard(user_id: str) -> dict:
    """Create the App Home dashboard view."""
    try:
        # Get real-time service status
        status_result = run_command("status --running", user_id)
        list_result = run_command("list", user_id)
        history_result = run_command("history --limit 3", user_id)
        
        # Get user's recent commands
        recent_commands = get_recent_commands(user_id, 3)
        
        # Build the home view
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🤖 TaskFlows Control Center"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Welcome <@{user_id}>! Manage your TaskFlows services from here."}
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*🚀 Quick Actions*"}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📊 Status"},
                        "action_id": "home_status",
                        "style": "primary"
                    },
                    {
                        "type": "button", 
                        "text": {"type": "plain_text", "text": "📋 List All"},
                        "action_id": "home_list"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📜 History"},
                        "action_id": "home_history"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔄 Refresh"},
                        "action_id": "refresh_home"
                    }
                ]
            },
            {
                "type": "divider"
            }
        ]
        
        # Add running services section
        if "No services found" not in status_result and "❌" not in status_result:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*🟢 Running Services*"}
            })
            
            # Truncate status for home view
            status_lines = status_result.split('\n')[:10]
            status_preview = '\n'.join(status_lines)
            if len(status_lines) == 10:
                status_preview += "\n... (view full status with button above)"
                
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```\n{status_preview}\n```"}
            })
        else:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*⚪ No Running Services*\nAll services are currently stopped."}
            })
        
        blocks.append({"type": "divider"})
        
        # Add recent commands section
        if recent_commands:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*📝 Recent Commands*"}
            })
            
            recent_text = "\n".join([f"• `{cmd}`" for cmd in recent_commands])
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": recent_text}
            })
            blocks.append({"type": "divider"})
        
        # Add service management section
        blocks.extend([
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*⚙️ Service Management*"}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "▶️ Start Service"},
                        "action_id": "start_service_modal"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "⏹️ Stop Service"},
                        "action_id": "stop_service_modal"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📄 View Logs"},
                        "action_id": "view_logs_modal"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🕐 Last updated: {datetime.now().strftime('%H:%M:%S')} | 💡 Use `/tf help` for command reference"
                    }
                ]
            }
        ])
        
        return {
            "type": "home",
            "blocks": blocks
        }
        
    except Exception as e:
        logger.error(f"Error creating app home dashboard: {e}")
        return {
            "type": "home",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"❌ Error loading dashboard: {str(e)}"}
                }
            ]
        }


@app.event("app_home_opened")
def handle_app_home_opened(event, client):
    """Handle when user opens the App Home."""
    user_id = event["user"]
    
    try:
        # Create and publish the home view
        home_view = create_app_home_dashboard(user_id)
        
        client.views_publish(
            user_id=user_id,
            view=home_view
        )
        
        logger.info(f"Published App Home for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error publishing App Home: {e}")


@app.action("refresh_home")
def handle_refresh_home(ack, body, client):
    """Handle refresh button in App Home."""
    ack()
    user_id = body["user"]["id"]
    
    try:
        # Recreate and update the home view
        home_view = create_app_home_dashboard(user_id)
        
        client.views_publish(
            user_id=user_id,
            view=home_view
        )
        
    except Exception as e:
        logger.error(f"Error refreshing App Home: {e}")


@app.action("home_status")
def handle_home_status(ack, body, client):
    """Handle status button from App Home."""
    ack()
    user_id = body["user"]["id"]
    
    if not check_rate_limit(user_id):
        return
    
    result = run_command("status", user_id)
    
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"*📊 Service Status*\n\n{format_for_slack(result, 'status')}"
    )


@app.action("home_list")
def handle_home_list(ack, body, client):
    """Handle list button from App Home."""
    ack()
    user_id = body["user"]["id"]
    
    if not check_rate_limit(user_id):
        return
    
    result = run_command("list", user_id)
    
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"*📋 All Services*\n\n{format_for_slack(result, 'list')}"
    )


@app.action("home_history")
def handle_home_history(ack, body, client):
    """Handle history button from App Home."""
    ack()
    user_id = body["user"]["id"]
    
    if not check_rate_limit(user_id):
        return
    
    result = run_command("history", user_id)
    
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"*📜 Task History*\n\n{format_for_slack(result, 'history')}"
    )


def create_service_selection_modal(action_type: str) -> dict:
    """Create a modal for selecting services."""
    try:
        # Get list of services
        services_result = run_command("list")
        services = []
        
        if services_result and "❌" not in services_result:
            for line in services_result.strip().split('\n'):
                if line.strip():
                    services.append(line.strip())
        
        # Create options for the select menu
        options = []
        for service in services[:25]:  # Slack limit
            options.append({
                "text": {"type": "plain_text", "text": service},
                "value": service
            })
        
        if not options:
            options.append({
                "text": {"type": "plain_text", "text": "No services available"},
                "value": "none"
            })
        
        action_titles = {
            "start": "▶️ Start Service",
            "stop": "⏹️ Stop Service", 
            "logs": "📄 View Service Logs"
        }
        
        return {
            "type": "modal",
            "callback_id": f"{action_type}_service_modal",
            "title": {"type": "plain_text", "text": action_titles.get(action_type, "Service Action")},
            "submit": {"type": "plain_text", "text": action_type.title()},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"Select a service to {action_type}:"}
                },
                {
                    "type": "section",
                    "accessory": {
                        "type": "static_select",
                        "placeholder": {"type": "plain_text", "text": "Choose a service"},
                        "action_id": "selected_service",
                        "options": options
                    },
                    "text": {"type": "mrkdwn", "text": "Service:"}
                }
            ]
        }
        
    except Exception as e:
        logger.error(f"Error creating service selection modal: {e}")
        return {
            "type": "modal",
            "callback_id": f"{action_type}_service_modal",
            "title": {"type": "plain_text", "text": "Error"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"❌ Error loading services: {str(e)}"}
                }
            ]
        }


@app.action("start_service_modal")
def handle_start_service_modal(ack, body, client):
    """Show modal for starting a service."""
    ack()
    
    modal = create_service_selection_modal("start")
    
    client.views_open(
        trigger_id=body["trigger_id"],
        view=modal
    )


@app.action("stop_service_modal")
def handle_stop_service_modal(ack, body, client):
    """Show modal for stopping a service."""
    ack()
    
    modal = create_service_selection_modal("stop")
    
    client.views_open(
        trigger_id=body["trigger_id"],
        view=modal
    )


@app.action("view_logs_modal")
def handle_view_logs_modal(ack, body, client):
    """Show modal for viewing service logs."""
    ack()
    
    modal = create_service_selection_modal("logs")
    
    client.views_open(
        trigger_id=body["trigger_id"],
        view=modal
    )


@app.view("start_service_modal")
def handle_start_service_submission(ack, body, client):
    """Handle service start submission."""
    ack()
    
    user_id = body["user"]["id"]
    selected_service = body["view"]["state"]["values"]["section"]["selected_service"]["selected_option"]["value"]
    
    if selected_service == "none":
        return
    
    if not check_rate_limit(user_id):
        return
    
    result = run_command(f"start {selected_service}", user_id)
    
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"*▶️ Starting Service: {selected_service}*\n\n{format_for_slack(result, 'start')}"
    )
    
    # Refresh the home view
    try:
        home_view = create_app_home_dashboard(user_id)
        client.views_publish(user_id=user_id, view=home_view)
    except Exception as e:
        logger.error(f"Error refreshing home after start: {e}")


@app.view("stop_service_modal")
def handle_stop_service_submission(ack, body, client):
    """Handle service stop submission."""
    ack()
    
    user_id = body["user"]["id"]
    selected_service = body["view"]["state"]["values"]["section"]["selected_service"]["selected_option"]["value"]
    
    if selected_service == "none":
        return
    
    if not check_rate_limit(user_id):
        return
    
    # Check if requires confirmation
    command = f"stop {selected_service}"
    needs_confirmation, confirmation_msg = requires_confirmation(command, user_id)
    
    if needs_confirmation:
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text=confirmation_msg
        )
        return
    
    result = run_command(command, user_id)
    
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"*⏹️ Stopping Service: {selected_service}*\n\n{format_for_slack(result, 'stop')}"
    )
    
    # Refresh the home view
    try:
        home_view = create_app_home_dashboard(user_id)
        client.views_publish(user_id=user_id, view=home_view)
    except Exception as e:
        logger.error(f"Error refreshing home after stop: {e}")


@app.view("logs_service_modal")
def handle_logs_service_submission(ack, body, client):
    """Handle service logs submission."""
    ack()
    
    user_id = body["user"]["id"]
    # Correctly extract the selected service from the view state
    try:
        state_values = body["view"]["state"]["values"]
        # The block_id and action_id might vary, find the correct keys
        block_id = next(iter(state_values))
        action_id = next(iter(state_values[block_id]))
        selected_service = state_values[block_id][action_id]["selected_option"]["value"]
    except (KeyError, StopIteration):
        logger.error(f"Could not find selected service in view state: {body['view']['state']['values']}")
        return

    if selected_service == "none":
        return
    
    if not check_rate_limit(user_id):
        return
    
    result = run_command(f"logs {selected_service}", user_id)
    
    display_logs(client, user_id, selected_service, result)


def display_logs(client, user_id: str, service: str, logs: str):
    """Display service logs, uploading as a file if the content is too long."""
    log_header = f"*📄 Logs for Service: {service}*"
    
    # Slack's message limit is 4000 characters. We use 3000 as a safe threshold.
    if len(logs) > 3000:
        try:
            # Use files_upload_v2 for modern file uploads
            client.files_upload_v2(
                channel=user_id,
                content=logs,
                title=f"Logs for {service}",
                filename=f"{service}-logs.txt",
                initial_comment=log_header,
            )
        except Exception as e:
            logger.error(f"Error uploading log file: {e}")
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text=f"{log_header}\n\n❌ An error occurred while trying to upload the log file."
            )
    else:
        # If logs are short, post them in an ephemeral message as before
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text=f"{log_header}\n\n{format_for_slack(logs, 'logs')}"
        )


def create_web_dashboard_blocks() -> list:
    """Create blocks that link to an external web dashboard."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn", 
                "text": "*🌐 Web Dashboard*\nView detailed metrics and logs in your browser"
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Open Dashboard"},
                "url": "http://localhost:3000",  # Grafana or custom dashboard URL
                "action_id": "open_web_dashboard"
            }
        }
    ]


def create_workflow_integration() -> dict:
    """Create workflow builder integration suggestions."""
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*🔄 Workflow Integration*\nCreate custom workflows in Slack's Workflow Builder:\n" +
                   "• Scheduled status reports\n" +
                   "• Alert escalation workflows\n" +
                   "• Service restart procedures\n" +
                   "Access via: Slack → Tools → Workflow Builder"
        }
    }


@app.command("/tf-dashboard")
def handle_dashboard_command(ack: Ack, command, client):
    """Dedicated dashboard slash command."""
    ack()
    user_id = command["user_id"]
    channel_id = command["channel_id"]
    
    if not is_authorized(user_id, channel_id):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="❌ You are not authorized to use this command."
        )
        return
    
    dashboard_type = command["text"].strip().lower()
    
    if dashboard_type == "modal":
        # Open modal dashboard
        modal_dashboard = create_modal_dashboard(user_id)
        client.views_open(
            trigger_id=command["trigger_id"], 
            view=modal_dashboard
        )
    elif dashboard_type == "web":
        # Show web dashboard info
        web_blocks = create_web_dashboard_blocks()
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            blocks=web_blocks
        )
    else:
        # Default: show channel dashboard
        dashboard = create_status_dashboard(user_id)
        client.chat_postMessage(
            channel=channel_id,
            text="🤖 *TaskFlows Dashboard*",
            **dashboard
        )


def create_modal_dashboard(user_id: str) -> dict:
    """Create a modal-based dashboard."""
    try:
        # Get current status
        status_result = run_command("status --running", user_id)
        
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "📊 TaskFlows Dashboard"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Current Status Overview*"}
            }
        ]
        
        if "No services found" not in status_result:
            status_lines = status_result.split('\n')[:8]  # Limit for modal
            status_text = '\n'.join(status_lines)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```\n{status_text}\n```"}
            })
        else:
            blocks.append({
                "type": "section", 
                "text": {"type": "mrkdwn", "text": "⚪ No services currently running"}
            })
        
        blocks.extend([
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📊 Full Status"},
                        "action_id": "modal_full_status"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📋 List All"},
                        "action_id": "modal_list_services"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🏠 Go to App Home"},
                        "action_id": "go_to_app_home"
                    }
                ]
            }
        ])
        
        return {
            "type": "modal",
            "callback_id": "dashboard_modal",
            "title": {"type": "plain_text", "text": "TaskFlows Dashboard"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": blocks
        }
        
    except Exception as e:
        logger.error(f"Error creating modal dashboard: {e}")
        return {
            "type": "modal",
            "callback_id": "dashboard_modal",
            "title": {"type": "plain_text", "text": "Error"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"❌ Error: {str(e)}"}
                }
            ]
        }


@app.action("modal_full_status")
def handle_modal_full_status(ack, body, client):
    """Handle full status from modal."""
    ack()
    user_id = body["user"]["id"]
    
    result = run_command("status", user_id)
    
    # Update modal with full status
    updated_modal = {
        "type": "modal",
        "callback_id": "status_modal",
        "title": {"type": "plain_text", "text": "Full Service Status"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*📊 Complete Service Status*\n\n```\n{result}\n```"}
            }
        ]
    }
    
    client.views_update(
        view_id=body["view"]["id"],
        view=updated_modal
    )


@app.action("modal_list_services")
def handle_modal_list_services(ack, body, client):
    """Handle list services from modal."""
    ack()
    user_id = body["user"]["id"]
    
    result = run_command("list", user_id)
    
    updated_modal = {
        "type": "modal",
        "callback_id": "list_modal",
        "title": {"type": "plain_text", "text": "All Services"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*📋 All Services*\n\n```\n{result}\n```"}
            }
        ]
    }
    
    client.views_update(
        view_id=body["view"]["id"],
        view=updated_modal
    )


@app.action("go_to_app_home")
def handle_go_to_app_home(ack, body, client):
    """Handle navigation to App Home."""
    ack()
    
    # Close modal and show message
    client.chat_postEphemeral(
        channel=body["user"]["id"],
        user=body["user"]["id"],
        text="🏠 Click on the TaskFlows app in your sidebar to view the App Home dashboard!"
    )

def main():
    """Entry point for the Slack bot CLI."""
    cli()


if __name__ == "__main__":
    main()