"""
Kaori API — Schemas Endpoints

Claim type schema discovery.
"""
from fastapi import APIRouter, HTTPException

from core import load_claim_schema, list_available_schemas
from .models import SchemaListResponse, SchemaDetailResponse

router = APIRouter()


@router.get("/schemas", response_model=SchemaListResponse)
async def list_schemas():
    """
    List all available claim type schemas.
    
    Returns IDs like: earth.flood.v1, ocean.coral_bleaching.v1
    """
    try:
        schemas = list_available_schemas()
        return SchemaListResponse(schemas=schemas)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schemas/{claim_type:path}", response_model=SchemaDetailResponse)
async def get_schema(claim_type: str):
    """
    Get schema details for a claim type.
    
    Example: /schemas/earth.flood.v1
    """
    try:
        schema = load_claim_schema(claim_type, validate=False)
        
        return SchemaDetailResponse(
            id=schema.get("id", claim_type),
            version=schema.get("version", 1),
            domain=schema.get("domain", ""),
            topic=schema.get("topic", ""),
            risk_profile=schema.get("risk_profile", "monitor"),
            config=schema,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Schema not found: {claim_type}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
