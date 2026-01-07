"""
Kaori API — Shared Dependencies

Holds the singleton instance of the Kaori Engine to ensure in-memory state
is shared across different API routers.
"""
from core import KaoriEngine
from core.validators import ValidationPipeline

# Global Singleton Engine
# In production, this would be replaced by a Database connection pool
# but the Engine itself might still be a singleton for caching/orchestration.
engine = KaoriEngine(auto_sign=True)

# Global Validation Pipeline
pipeline = ValidationPipeline()
