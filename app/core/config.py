"""
Settings loaded from environment variables (via .env locally, real env
vars in ECS). Using pydantic-settings so config is validated at startup
rather than failing with a confusing error deep in some request handler.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/money_tracking_app"
    environment: str = "local"

    class Config:
        env_file = ".env"


settings = Settings()
