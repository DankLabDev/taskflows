from pydantic_settings import BaseSettings, SettingsConfigDict


class SlackConfig(BaseSettings):
    """Slack app configuration settings."""
    bot_token: str
    signing_secret: str
    app_token: str = ""  # For socket mode, optional
    allowed_users: list[str] = []  # Slack user IDs who can use the bot
    allowed_channels: list[str] = []  # Channel IDs where the bot can be used
    use_socket_mode: bool = False  # Use Socket Mode instead of HTTP
    
    model_config = SettingsConfigDict(env_prefix="taskflows_slack_")


config = SlackConfig()
