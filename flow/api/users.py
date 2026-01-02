"""
Kaori API — Users Endpoints

User standing and credits.
"""
from fastapi import APIRouter, HTTPException

from .models import UserStandingResponse, UserCreditsResponse

router = APIRouter()

# Mock user data (replace with database)
_mock_users = {
    "user123": {
        "standing": "bronze",
        "trust_score": 0.5,
        "verified_observations": 12,
        "validation_accuracy": 0.78,
        "tenure_days": 45,
        "total_credits": 240,
        "available_credits": 200,
        "lifetime_earned": 340,
    },
    "expert456": {
        "standing": "expert",
        "trust_score": 0.92,
        "verified_observations": 156,
        "validation_accuracy": 0.95,
        "tenure_days": 365,
        "total_credits": 4500,
        "available_credits": 3200,
        "lifetime_earned": 8900,
    },
}


@router.get("/users/{user_id}/standing", response_model=UserStandingResponse)
async def get_user_standing(user_id: str):
    """
    Get user's current standing and trust metrics.
    """
    if user_id not in _mock_users:
        # Return default for unknown users
        return UserStandingResponse(
            user_id=user_id,
            standing="bronze",
            trust_score=0.5,
            verified_observations=0,
            validation_accuracy=0.0,
            tenure_days=0,
        )
    
    user = _mock_users[user_id]
    return UserStandingResponse(
        user_id=user_id,
        standing=user["standing"],
        trust_score=user["trust_score"],
        verified_observations=user["verified_observations"],
        validation_accuracy=user["validation_accuracy"],
        tenure_days=user["tenure_days"],
    )


@router.get("/users/{user_id}/credits", response_model=UserCreditsResponse)
async def get_user_credits(user_id: str):
    """
    Get user's Kaori Credits balance.
    """
    if user_id not in _mock_users:
        return UserCreditsResponse(
            user_id=user_id,
            total_credits=0,
            available_credits=0,
            lifetime_earned=0,
        )
    
    user = _mock_users[user_id]
    return UserCreditsResponse(
        user_id=user_id,
        total_credits=user["total_credits"],
        available_credits=user["available_credits"],
        lifetime_earned=user["lifetime_earned"],
    )
