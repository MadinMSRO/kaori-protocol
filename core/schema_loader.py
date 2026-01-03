"""
Kaori Core — Schema Loader

Load and validate ClaimType YAML files against the JSON Schema.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml


def get_schemas_dir() -> Path:
    """Get the schemas directory path."""
    # Navigate from core/ to project root to schemas/
    core_dir = Path(__file__).parent
    project_root = core_dir.parent
    return project_root / "schemas"


def get_meta_schema_path() -> Path:
    """Get the path to the ClaimType JSON Schema."""
    return get_schemas_dir() / "meta" / "claimtype.schema.json"


@lru_cache(maxsize=32)
def load_claim_schema(claim_type_id: str, validate: bool = True) -> dict:
    """
    Load a ClaimType YAML schema by its ID.
    
    Args:
        claim_type_id: Canonical ID like "earth.flood.v1"
        validate: Whether to validate against JSON Schema
        
    Returns:
        Parsed YAML as dict
        
    Raises:
        FileNotFoundError: If schema file not found
        ValueError: If schema fails validation
    """
    # Parse claim_type_id: domain.topic.vN
    parts = claim_type_id.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid claim_type_id format: {claim_type_id}")
    
    domain = parts[0]
    topic = parts[1]
    version = parts[2]  # e.g., "v1"
    
    # Construct file path
    version_num = version.replace("v", "")
    filename = f"{topic}_v{version_num}.yaml"
    schema_path = get_schemas_dir() / domain / filename
    
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    
    # Load YAML
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    
    # Optionally validate against JSON Schema
    if validate:
        validate_claim_schema(schema, schema_path)
    
    return schema


def validate_claim_schema(schema: dict, source_path: Optional[Path] = None) -> None:
    """
    Validate a loaded schema against the ClaimType JSON Schema.
    
    Args:
        schema: The parsed YAML schema
        source_path: Path for error messages
        
    Raises:
        ValueError: If validation fails
    """
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        # jsonschema not installed, skip validation
        return
    
    meta_schema_path = get_meta_schema_path()
    if not meta_schema_path.exists():
        # No meta schema, skip validation
        return
    
    with open(meta_schema_path, "r", encoding="utf-8") as f:
        meta_schema = json.load(f)
    
    validator = Draft202012Validator(meta_schema)
    errors = list(validator.iter_errors(schema))
    
    if errors:
        error_msg = f"Schema validation failed for {source_path or 'unknown'}:\n"
        for e in errors[:5]:
            path = ".".join(str(p) for p in e.path) if e.path else "<root>"
            error_msg += f"  - {path}: {e.message}\n"
        raise ValueError(error_msg)


def list_available_schemas() -> list[str]:
    """
    List all available ClaimType schema IDs.
    
    Returns:
        List of claim_type_ids like ["earth.flood.v1", "ocean.coral_bleaching.v1"]
    """
    schemas_dir = get_schemas_dir()
    result = []
    
    for domain_dir in schemas_dir.iterdir():
        if not domain_dir.is_dir():
            continue
        if domain_dir.name == "meta":
            continue
        
        domain = domain_dir.name
        for yaml_file in domain_dir.glob("*.yaml"):
            # Parse filename: topic_v1.yaml
            stem = yaml_file.stem  # e.g., "flood_v1"
            if "_v" not in stem:
                continue
            
            parts = stem.rsplit("_v", 1)
            topic = parts[0]
            version = f"v{parts[1]}"
            
            claim_id = f"{domain}.{topic}.{version}"
            result.append(claim_id)
    
    return sorted(result)


def get_claim_config(claim_type: str) -> dict:
    """
    Convenience wrapper to load claim configuration.
    
    Args:
        claim_type: Claim type ID like "earth.flood.v1"
        
    Returns:
        Claim configuration dict
    """
    return load_claim_schema(claim_type)


def get_claim_type(claim_type_id: str) -> "ClaimType":
    """
    Load a ClaimType as a typed Pydantic model.
    
    This provides structured, type-safe access to claim configuration.
    
    Args:
        claim_type_id: Claim type ID like "earth.flood.v1"
        
    Returns:
        ClaimType model instance
        
    Example:
        >>> ct = get_claim_type("earth.flood.v1")
        >>> ct.consensus_model.finalize_threshold
        15
        >>> ct.requires_human_gate()
        True
    """
    from .claimtype import ClaimType
    
    raw_config = load_claim_schema(claim_type_id, validate=False)
    return ClaimType.model_validate(raw_config)
