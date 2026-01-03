"""
Kaori API — Authentication

JWT token and API key authentication for the Kaori Protocol API.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, status, Header, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from jose import JWTError, jwt
from pydantic import BaseModel

from core.models import Standing
from .config import get_settings


# =============================================================================
# Security Schemes
# =============================================================================

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# =============================================================================
# Models
# =============================================================================

class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # User ID
    standing: str = "bronze"
    exp: datetime
    iat: datetime
    jti: str  # Token ID for revocation


class AuthenticatedUser(BaseModel):
    """Represents an authenticated user or service."""
    user_id: str
    standing: Standing
    auth_method: str  # "jwt" or "api_key"
    

class TokenResponse(BaseModel):
    """Response when issuing a new token."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user_id: str
    standing: str


# =============================================================================
# Token Functions
# =============================================================================

def create_access_token(
    user_id: str,
    standing: str = "bronze",
    expires_delta: Optional[timedelta] = None,
) -> TokenResponse:
    """
    Create a new JWT access token.
    
    Args:
        user_id: The user's unique identifier
        standing: The user's standing class
        expires_delta: Optional custom expiration time
        
    Returns:
        TokenResponse with the access token and metadata
    """
    settings = get_settings()
    
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expire_minutes)
    
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    
    payload = {
        "sub": user_id,
        "standing": standing,
        "exp": expire,
        "iat": now,
        "jti": str(uuid4()),
    }
    
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    
    return TokenResponse(
        access_token=token,
        expires_in=int(expires_delta.total_seconds()),
        user_id=user_id,
        standing=standing,
    )


def verify_token(token: str) -> TokenPayload:
    """
    Verify and decode a JWT token.
    
    Args:
        token: The JWT token string
        
    Returns:
        TokenPayload with decoded claims
        
    Raises:
        HTTPException: If token is invalid or expired
    """
    settings = get_settings()
    
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return TokenPayload(**payload)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_api_key(api_key: str) -> bool:
    """
    Verify an API key.
    
    Args:
        api_key: The API key to verify
        
    Returns:
        True if valid, False otherwise
    """
    settings = get_settings()
    return api_key in settings.api_key_list


# =============================================================================
# FastAPI Dependencies
# =============================================================================

async def get_current_user(
    bearer_token: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)] = None,
    api_key: Annotated[Optional[str], Security(api_key_header)] = None,
) -> AuthenticatedUser:
    """
    Get the current authenticated user from JWT or API key.
    
    This is the main authentication dependency. Use it on protected endpoints:
    
        @router.post("/protected")
        async def protected_endpoint(user: AuthenticatedUser = Depends(get_current_user)):
            ...
    """
    # Try JWT token first
    if bearer_token and bearer_token.credentials:
        token_data = verify_token(bearer_token.credentials)
        try:
            # Standing enum values are lowercase (bronze, silver, expert, authority)
            standing = Standing(token_data.standing.lower())
        except ValueError:
            standing = Standing.BRONZE
        return AuthenticatedUser(
            user_id=token_data.sub,
            standing=standing,
            auth_method="jwt",
        )
    
    # Try API key
    if api_key:
        if verify_api_key(api_key):
            # API keys get "service" standing (treated as expert for most purposes)
            return AuthenticatedUser(
                user_id=f"service:{api_key[:8]}...",
                standing=Standing.EXPERT,
                auth_method="api_key",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
    
    # No auth provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide JWT token or API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_user(
    bearer_token: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)] = None,
    api_key: Annotated[Optional[str], Security(api_key_header)] = None,
) -> Optional[AuthenticatedUser]:
    """
    Get the current user if authenticated, None otherwise.
    
    Use this for endpoints that work both authenticated and unauthenticated,
    but may provide different data based on auth status.
    """
    try:
        return await get_current_user(bearer_token, api_key)
    except HTTPException:
        return None


def require_standing(min_standing: str):
    """
    Factory for creating a dependency that requires minimum standing.
    
    Usage:
        @router.post("/admin-only")
        async def admin_endpoint(
            user: AuthenticatedUser = Depends(require_standing("authority"))
        ):
            ...
    """
    standing_order = ["bronze", "silver", "expert", "authority"]
    min_index = standing_order.index(min_standing.lower())
    
    async def check_standing(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        try:
            user_index = standing_order.index(user.standing.value.lower())
        except ValueError:
            user_index = 0
        
        if user_index < min_index:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient standing. Required: {min_standing}, Your standing: {user.standing.value}",
            )
        return user
    
    return check_standing


# =============================================================================
# Convenience exports
# =============================================================================

# Pre-built standing requirements
require_bronze = require_standing("bronze")
require_silver = require_standing("silver")
require_expert = require_standing("expert")
require_authority = require_standing("authority")
