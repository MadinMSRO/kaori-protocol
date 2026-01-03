"""
Kaori API — Authentication Endpoints

Token issuance and authentication endpoints.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

from .auth import (
    create_access_token,
    get_current_user,
    AuthenticatedUser,
    TokenResponse,
)


router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class LoginRequest(BaseModel):
    """Login request with user credentials."""
    user_id: str
    password: str  # In production, verify against user database


class TokenRefreshRequest(BaseModel):
    """Request to refresh an existing token."""
    pass  # Uses current token from header


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/auth/token", response_model=TokenResponse, tags=["Auth"])
async def login(request: LoginRequest):
    """
    Authenticate and receive a JWT token.
    
    In production, this would verify credentials against a user database.
    For demo purposes, any user_id with password "kaori" is accepted.
    """
    # Demo authentication - in production, verify against user database
    if request.password != "kaori":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    
    # Look up user standing from database
    # For demo, assign standing based on user_id prefix
    standing = "bronze"
    if request.user_id.startswith("expert_"):
        standing = "expert"
    elif request.user_id.startswith("silver_"):
        standing = "silver"
    elif request.user_id.startswith("authority_") or request.user_id.startswith("admin_"):
        standing = "authority"
    
    return create_access_token(user_id=request.user_id, standing=standing)


@router.post("/auth/refresh", response_model=TokenResponse, tags=["Auth"])
async def refresh_token(user: AuthenticatedUser = Depends(get_current_user)):
    """
    Refresh an existing token.
    
    Requires a valid JWT token. Returns a new token with refreshed expiration.
    """
    return create_access_token(
        user_id=user.user_id,
        standing=user.standing.value,
    )


@router.get("/auth/me", tags=["Auth"])
async def get_me(user: AuthenticatedUser = Depends(get_current_user)):
    """
    Get current authenticated user info.
    
    Returns the user ID, standing, and auth method for the current token.
    """
    return {
        "user_id": user.user_id,
        "standing": user.standing.value,
        "auth_method": user.auth_method,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
