"""
Settings loaded from environment variables (via .env locally, real env
vars in ECS). Using pydantic-settings so config is validated at startup
rather than failing with a confusing error deep in some request handler.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/money_tracking_app"
    environment: str = "local"

    # extra="ignore" -- .env also carries PLAID_*/AWS_* vars that other
    # modules read directly via os.environ (app/core/plaid_client.py,
    # boto3's own credential chain), not through this Settings class.
    # Without this, pydantic-settings treats any key in .env that isn't
    # a declared field above as a validation error.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
