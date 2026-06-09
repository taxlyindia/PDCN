from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "MultiTenant CRM"
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/crm_db"

    JWT_SECRET_KEY: str = "jwt-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "noreply@yourcrm.com"

    FRONTEND_URL: str = "http://localhost:8000"

    SUPER_ADMIN_EMAIL: str = "admin@yourcrm.com"
    SUPER_ADMIN_PASSWORD: str = "SuperAdmin@123"
    SUPER_ADMIN_NAME: str = "Super Admin"

    TRIAL_DAYS: int = 10

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
