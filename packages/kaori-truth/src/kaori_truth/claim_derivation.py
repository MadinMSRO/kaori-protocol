"""
Kaori Truth — Claim Payload Derivation

Deterministic derivation of claim output from observations.

INVARIANT: claim_payload = f(observations, trust_snapshot, claim_type, truth_key)

The claim payload is DERIVED, not supplied externally. This preserves
Kaori's core integrity guarantee that TruthState is a pure function
of Bronze-layer observations.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from kaori_truth.canonical.json import canonical_dict


class ClaimDerivationError(Exception):
    """Error during claim payload derivation."""
    pass


def derive_claim_payload(
    observations: List["Observation"],
    trust_snapshot: "TrustSnapshot",
    claim_type: "ClaimType",
    truth_key: str,
    *,
    aggregate: Optional[dict] = None,
) -> dict:
    """
    Derive claim payload deterministically from observations.
    
    This is the ONLY correct way to produce TruthState.claim.
    External claim payloads are NOT accepted by default.
    
    The derivation rules are:
    1. Aggregate observation payloads (weighted by power)
    2. Apply ClaimType policy (consensus rules)
    3. Produce deterministic claim output
    
    Args:
        observations: List of Bronze-layer observations
        trust_snapshot: Frozen trust state for power weighting
        claim_type: ClaimType with derivation rules
        truth_key: For context (domain/topic)
        aggregate: Optional pre-computed aggregate metrics
        
    Returns:
        Deterministic claim payload (ready for schema validation)
        
    Raises:
        ClaimDerivationError: If derivation fails
    """
    if not observations:
        raise ClaimDerivationError("Cannot derive claim from empty observations")
    
    # Get derivation policy from ClaimType
    domain = claim_type.domain.lower()
    topic = claim_type.topic.lower()
    
    # Dispatch to domain-specific derivation
    if domain == "earth":
        return _derive_earth_claim(observations, trust_snapshot, claim_type, aggregate)
    elif domain == "ocean":
        return _derive_ocean_claim(observations, trust_snapshot, claim_type, aggregate)
    elif domain == "space":
        return _derive_space_claim(observations, trust_snapshot, claim_type, aggregate)
    elif domain == "meta":
        return _derive_meta_claim(observations, trust_snapshot, claim_type, aggregate)
    else:
        # Fallback: generic aggregation
        return _derive_generic_claim(observations, trust_snapshot, claim_type, aggregate)


def _derive_earth_claim(
    observations: List["Observation"],
    trust_snapshot: "TrustSnapshot",
    claim_type: "ClaimType",
    aggregate: Optional[dict],
) -> dict:
    """Derive claim for earth domain (flood, landslide, etc.)."""
    
    # Aggregate observation payloads weighted by power
    weighted_payloads = []
    total_power = 0.0
    
    for obs in observations:
        power = trust_snapshot.get_power(obs.reporter_id)
        weighted_payloads.append((obs.payload, power))
        total_power += power
    
    # Extract common fields and compute consensus
    claim = {}
    
    # Severity: weighted mode
    severity_weights = {}
    for payload, power in weighted_payloads:
        severity = payload.get("severity", "unknown")
        severity_weights[severity] = severity_weights.get(severity, 0) + power
    
    if severity_weights:
        claim["severity"] = max(severity_weights.keys(), key=lambda k: severity_weights[k])
    else:
        claim["severity"] = "unknown"
    
    # Water level: weighted average (if present)
    water_levels = []
    water_power = 0.0
    for payload, power in weighted_payloads:
        if "water_level" in payload:
            try:
                level = float(payload["water_level"])
                water_levels.append(level * power)
                water_power += power
            except (ValueError, TypeError):
                pass
    
    if water_levels and water_power > 0:
        claim["water_level_meters"] = round(sum(water_levels) / water_power, 2)
    
    # Observation count
    claim["observation_count"] = len(observations)
    claim["network_trust"] = round(total_power, 2)
    
    return canonical_dict(claim)


def _derive_ocean_claim(
    observations: List["Observation"],
    trust_snapshot: "TrustSnapshot", 
    claim_type: "ClaimType",
    aggregate: Optional[dict],
) -> dict:
    """Derive claim for ocean domain (coral bleaching, etc.)."""
    # Similar to earth but may add z_index specific logic
    return _derive_earth_claim(observations, trust_snapshot, claim_type, aggregate)


def _derive_space_claim(
    observations: List["Observation"],
    trust_snapshot: "TrustSnapshot",
    claim_type: "ClaimType",
    aggregate: Optional[dict],
) -> dict:
    """Derive claim for space domain (debris tracking, etc.)."""
    weighted_payloads = []
    total_power = 0.0
    
    for obs in observations:
        power = trust_snapshot.get_power(obs.reporter_id)
        weighted_payloads.append((obs.payload, power))
        total_power += power
    
    claim = {
        "observation_count": len(observations),
        "network_trust": round(total_power, 2),
    }
    
    # Aggregate any shared fields
    for payload, power in weighted_payloads:
        for key, value in payload.items():
            if key not in claim and isinstance(value, (str, int, float, bool)):
                claim[key] = value  # First observation wins for simple fields
    
    return canonical_dict(claim)


def _derive_meta_claim(
    observations: List["Observation"],
    trust_snapshot: "TrustSnapshot",
    claim_type: "ClaimType",
    aggregate: Optional[dict],
) -> dict:
    """
    Derive claim for meta domain (research artifacts, datasets, etc.).
    
    Meta claims typically validate/aggregate external evidence rather than
    direct observations. The claim output represents the validated state.
    """
    weighted_payloads = []
    total_power = 0.0
    
    for obs in observations:
        power = trust_snapshot.get_power(obs.reporter_id)
        weighted_payloads.append((obs.payload, power))
        total_power += power
    
    claim = {
        "observation_count": len(observations),
        "network_trust": round(total_power, 2),
    }
    
    # For meta claims, aggregate boolean validations
    valid_power = 0.0
    invalid_power = 0.0
    
    for payload, power in weighted_payloads:
        is_valid = payload.get("valid", payload.get("is_valid", None))
        if is_valid is True:
            valid_power += power
        elif is_valid is False:
            invalid_power += power
    
    # Consensus on validity
    if valid_power + invalid_power > 0:
        claim["valid"] = valid_power > invalid_power
        claim["validity_confidence"] = round(
            max(valid_power, invalid_power) / (valid_power + invalid_power), 4
        )
    
    return canonical_dict(claim)


def _derive_generic_claim(
    observations: List["Observation"],
    trust_snapshot: "TrustSnapshot",
    claim_type: "ClaimType",
    aggregate: Optional[dict],
) -> dict:
    """Generic claim derivation for unknown domains."""
    total_power = sum(
        trust_snapshot.get_power(obs.reporter_id) 
        for obs in observations
    )
    
    return canonical_dict({
        "observation_count": len(observations),
        "network_trust": round(total_power, 2),
    })


# Type hints for forward references
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from kaori_truth.primitives.observation import Observation
    from kaori_truth.primitives.claimtype import ClaimType
    from kaori_truth.trust_snapshot import TrustSnapshot
