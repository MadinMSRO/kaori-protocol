"""
Kaori API — Missions Endpoints

Mission discovery and management (FLOW_SPEC).
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from .models import MissionCreate, MissionResponse, MissionListResponse

router = APIRouter()

# In-memory mission store (replace with database)
_missions: dict[UUID, dict] = {}


@router.get("/missions", response_model=MissionListResponse)
async def list_missions(
    claim_type: str | None = None,
    status: str = "active",
    limit: int = 20,
    offset: int = 0,
):
    """
    List available missions.
    
    Missions are region/time-bound tasks for crowdsourced data collection.
    """
    missions = list(_missions.values())
    
    # Filter by claim type
    if claim_type:
        missions = [m for m in missions if m["claim_type"] == claim_type]
    
    # Filter by status
    missions = [m for m in missions if m["status"] == status]
    
    # Paginate
    total = len(missions)
    missions = missions[offset:offset + limit]
    
    return MissionListResponse(
        missions=[MissionResponse(**m) for m in missions],
        total=total,
    )


@router.post("/missions", response_model=MissionResponse)
async def create_mission(data: MissionCreate):
    """
    Create a new mission.
    
    Requires authority standing (not enforced in demo).
    """
    mission_id = uuid4()
    mission = {
        "mission_id": mission_id,
        "claim_type": data.claim_type,
        "status": "active",
        "scope": data.scope,
        "requirements": data.requirements,
        "rewards": data.rewards,
        "created_at": datetime.now(timezone.utc),
    }
    
    _missions[mission_id] = mission
    
    return MissionResponse(**mission)


@router.get("/missions/{mission_id}", response_model=MissionResponse)
async def get_mission(mission_id: UUID):
    """
    Get mission details.
    """
    if mission_id not in _missions:
        raise HTTPException(status_code=404, detail=f"Mission not found: {mission_id}")
    
    return MissionResponse(**_missions[mission_id])
