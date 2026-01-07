"""
Kaori API — FastAPI Application

Main entry point for the Kaori Protocol API.
"""
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .models import HealthResponse

# Import routers
from .observations import router as observations_router
from .truth import router as truth_router
from .votes import router as votes_router
from .probes import router as probes_router
from .users import router as users_router
from .schemas import router as schemas_router
from .auth_routes import router as auth_router

# =============================================================================
# Application
# =============================================================================

app = FastAPI(
    title="Kaori Protocol API",
    description="The Operating System for Reality — Ground Truth Verification",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# =============================================================================
# CORS Middleware
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Include Routers
# =============================================================================

# Public routes
app.include_router(auth_router, prefix="/api/v1", tags=["Auth"])
app.include_router(schemas_router, prefix="/api/v1", tags=["Schemas"])

# Protected routes (auth required)
app.include_router(observations_router, prefix="/api/v1", tags=["Observations"])
app.include_router(truth_router, prefix="/api/v1", tags=["Truth"])
app.include_router(votes_router, prefix="/api/v1", tags=["Votes"])
app.include_router(probes_router, prefix="/api/v1", tags=["Probes"])
app.include_router(users_router, prefix="/api/v1", tags=["Users"])


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/", tags=["System"])
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Kaori Protocol API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
