"""
Kaori Truth — Claim Payload Derivation

Deterministic derivation of claim output from observations.

INVARIANT: claim_payload = f(observations, trust_snapshot, claim_type, truth_key)

The claim payload is DERIVED, not supplied externally. This preserves
Kaori's core integrity guarantee that TruthState is a pure function
of Bronze-layer observations.

TruthState.claim is filled ONLY from ClaimType.output_schema properties.
The compiler MUST NOT invent keys, MUST NOT read ui_schema, and MUST NOT
guess a generic {severity, network_trust} payload when output_schema is absent.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from kaori_truth.canonical.json import canonical_dict

if TYPE_CHECKING:
    from kaori_truth.primitives.claimtype import ClaimType
    from kaori_truth.primitives.observation import Observation
    from kaori_truth.trust_snapshot import TrustSnapshot

# Sentinel: property had no usable observation values
_MISSING = object()

# Values collected from one observation for one output_schema property
_Value = Tuple[Any, float, str]


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

    Derivation:
    1. Require ClaimType.output_schema.properties (no ui_schema fallback)
    2. For each property, power-weight values from observation payloads
       (numbers averaged, booleans/enums consensus, arrays/objects highest power)
    3. Emit only those property keys — never invented extras

    Args:
        observations: List of Bronze-layer observations
        trust_snapshot: Frozen trust state for power weighting
        claim_type: ClaimType with output_schema
        truth_key: For context (domain/topic); unused in aggregation
        aggregate: Optional pre-computed metrics (unused; not claim keys)

    Returns:
        Deterministic claim payload (ready for schema validation)

    Raises:
        ClaimDerivationError: If derivation fails (including missing output_schema)
    """
    if not observations:
        raise ClaimDerivationError("Cannot derive claim from empty observations")

    output_schema = getattr(claim_type, "output_schema", None)
    if not output_schema:
        raise ClaimDerivationError(
            "ClaimType missing output_schema; cannot derive TruthState.claim"
        )

    properties = output_schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ClaimDerivationError(
            "ClaimType output_schema has no properties; cannot derive TruthState.claim"
        )

    weighted = _weighted_observations(observations, trust_snapshot)
    claim: Dict[str, Any] = {}

    for key, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            prop_schema = {}
        value = _aggregate_property(key, prop_schema, weighted)
        if value is not _MISSING:
            claim[key] = value

    return canonical_dict(claim)


def _weighted_observations(
    observations: List["Observation"],
    trust_snapshot: "TrustSnapshot",
) -> List[Tuple["Observation", float]]:
    """Pair each observation with reporter power (0 if unknown)."""
    weighted = []
    for obs in observations:
        power = trust_snapshot.get_trust(obs.reporter_id)
        weighted.append((obs, power))
    return weighted


def _values_for_key(
    key: str,
    weighted: List[Tuple["Observation", float]],
) -> List[_Value]:
    """Collect payload[key] from observations that declared it."""
    values: List[_Value] = []
    for obs, power in weighted:
        payload = obs.payload or {}
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            continue
        values.append((value, power, str(obs.observation_id)))
    return values


def _aggregate_property(
    key: str,
    prop_schema: Dict[str, Any],
    weighted: List[Tuple["Observation", float]],
) -> Any:
    """Aggregate one output_schema property from observation payloads."""
    values = _values_for_key(key, weighted)
    if not values:
        return _MISSING

    schema_type = prop_schema.get("type")
    if schema_type in ("number", "integer"):
        return _aggregate_number(values, schema_type)
    if schema_type == "boolean":
        return _aggregate_consensus(values, _is_bool)
    if schema_type == "string":
        return _aggregate_consensus(values, lambda v: isinstance(v, str))
    if schema_type in ("array", "object"):
        typed = [
            item for item in values
            if _matches_container_type(item[0], schema_type)
        ]
        if not typed:
            return _MISSING
        return _highest_power_value(typed)
    # Untyped property (or enum-only): highest-power value, no invented key
    return _highest_power_value(values)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _matches_container_type(value: Any, schema_type: str) -> bool:
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    return False


def _aggregate_number(values: List[_Value], schema_type: str) -> Any:
    numeric = [(v, p, oid) for v, p, oid in values if _is_number(v)]
    if not numeric:
        return _MISSING
    if len(numeric) == 1:
        value = numeric[0][0]
        if schema_type == "integer":
            return int(value)
        return value

    total_power = sum(p for _, p, _ in numeric)
    if total_power <= 0:
        total_power = float(len(numeric))
        weights = [(v, 1.0) for v, _, _ in numeric]
    else:
        weights = [(v, p) for v, p, _ in numeric]

    average = sum(v * p for v, p in weights) / total_power
    if schema_type == "integer":
        return int(round(average))
    return average


def _aggregate_consensus(values: List[_Value], type_check) -> Any:
    typed = [(v, p, oid) for v, p, oid in values if type_check(v)]
    if not typed:
        return _MISSING

    weights: Dict[Any, float] = {}
    for value, power, _oid in typed:
        weights[value] = weights.get(value, 0.0) + power

    # Deterministic: highest weight, then stable repr for ties
    return max(weights.keys(), key=lambda k: (weights[k], repr(k)))


def _highest_power_value(values: List[_Value]) -> Any:
    """Highest reporter power wins; observation_id breaks ties."""
    return max(values, key=lambda item: (item[1], item[2]))[0]
