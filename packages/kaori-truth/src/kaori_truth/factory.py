"""
Kaori Truth — Factory (The Temple Boundary)

This module is the "Bridge" between the dirty IO world and the pure Truth world.

ARCHITECTURAL RULE:
- This module imports from `kaori_truth.io` (Dirty)
- This module imports from `kaori_truth.primitives` (Pure)
- It constructs Pure objects from Dirty inputs.

Usage:
    from kaori_truth.factory import load_claim_type
    
    # Returns a pure ClaimType object with fully resolved schemas
    ct = load_claim_type("claim.yaml") 
"""
from pathlib import Path
from typing import Optional

from kaori_truth.io.loaders import load_yaml_file, resolve_schema_ref
from kaori_truth.primitives.claimtype import (
    ClaimType, TruthKeyConfig, ConsensusModel, 
    AutovalidationConfig, TemporalDecayConfig
)

def load_claim_type(path: str | Path, schema_base_path: str = "") -> ClaimType:
    """
    Load and construct a pure ClaimType from a YAML file.
    
    This function:
    1. Reads the YAML (IO)
    2. Resolves any schema references (IO)
    3. Injects the resolved schema into the ClaimType (Construction)
    4. Returns a pure ClaimType ready for compilation
    """
    raw_config = load_yaml_file(path)
    
    # Resolve Output Schema
    # If output_schema_ref is present, we load it NOW, so the ClaimType holds the data.
    output_schema = raw_config.get("output_schema")
    output_schema_ref = raw_config.get("output_schema_ref")
    
    if not output_schema and output_schema_ref:
        # Perform IO to load the schema
        resolved_schema = resolve_schema_ref(output_schema_ref, base_path=schema_base_path)
        output_schema = resolved_schema
    
    # Construct Pure Object
    claim_type = ClaimType(
        id=raw_config.get("id", ""),
        version=raw_config.get("version", 1),
        domain=raw_config.get("domain", "earth"),
        topic=raw_config.get("topic", ""),
        risk_profile=raw_config.get("risk_profile", "monitor"),
        truthkey=TruthKeyConfig(**raw_config.get("truthkey", {})),
        consensus_model=ConsensusModel(**raw_config.get("consensus_model", {})),
        autovalidation=AutovalidationConfig(**raw_config.get("autovalidation", {})),
        temporal_decay=TemporalDecayConfig(**raw_config.get("temporal_decay", {})),
        
        # Inject resolved schema
        output_schema=output_schema,
        output_schema_ref=output_schema_ref
    )
    
    claim_type._raw_config = raw_config
    return claim_type
