from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/ticketing"
    jwt_secret: str = "change-this-secret"
    access_token_expire_minutes: int = 60
    cancellation_window_hours: int = 24

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
