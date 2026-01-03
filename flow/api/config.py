"""
Kaori API — Configuration

Environment-based configuration for the API.
"""
import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """API Configuration loaded from environment variables."""
    
    # JWT Settings
    jwt_secret: str = "kaori-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    
    # API Keys (comma-separated list)
    api_keys: str = "dev-api-key-1,dev-api-key-2"
    
    # Rate Limiting
    rate_limit_per_minute: int = 60
    
    # CORS Origins (comma-separated)
    cors_origins: str = "*"
    
    # Environment
    environment: str = "development"
    
    class Config:
        env_prefix = "KAORI_"
        env_file = ".env"
        extra = "ignore"
    
    @property
    def api_key_list(self) -> list[str]:
        """Parse API keys from comma-separated string."""
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]
    
    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
    
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
