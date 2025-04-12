import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    
    # JWT
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Service URLs
    SEARCH_SERVICE_URL: str = "http://localhost:8001/search/"
    USERS_SERVICE_URL: str = "http://localhost:8002/users/"
    MERCHANTS_SERVICE_URL: str = "http://localhost:8003/merchants/"
    REDIS_URL: str = "redis://localhost:6379/0"

    # # Optional: Default Admin
    # ADMIN_EMAIL: str | None = None
    # ADMIN_PASSWORD: str | None = None


settings = Settings()