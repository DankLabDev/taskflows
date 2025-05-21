import click

from taskflows import logger

from .bot import start_bot


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
3. Create a slash command "/tf" with the URL to your bot
4. Install the app to your workspace
5. Set these environment variables:
   - TASKFLOWS_SLACK_BOT_TOKEN=xoxb-your-token
   - TASKFLOWS_SLACK_SIGNING_SECRET=your-signing-secret
   - TASKFLOWS_SLACK_ALLOWED_USERS=U12345,U67890 (optional)
   - TASKFLOWS_SLACK_ALLOWED_CHANNELS=C12345,C67890 (optional)
   - TASKFLOWS_SLACK_USE_SOCKET_MODE=true (optional)
   - TASKFLOWS_SLACK_APP_TOKEN=xapp-your-token (required if using socket mode)
6. Run "tf-slack start" to start the bot
""")


def main():
    """Entry point for the Slack bot CLI."""
    cli()


if __name__ == "__main__":
    main()
