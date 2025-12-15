from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "SwiftKyc"
    API_V1_PREFIX: str = "/api/v1"

    POSTGRES_DSN: str = "postgresql+asyncpg://swiftkyc:secretpassword@postgres:5432/swiftkycdb"

    REDIS_URL: str = "redis://redis:6379/0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
