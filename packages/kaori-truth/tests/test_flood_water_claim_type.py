"""earth.flood_water.v1: the product flood contract (Liminal).

A presence/absence and extent claim with the same rules as the Open Core
example earth.flood.v1, plus an output_schema, so a compiled TruthState
carries the reported flood. earth.flood.v1 keeps
failing compile by design (test_claim_derivation).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from kaori_truth import compile_truth_state
from kaori_truth.factory import load_claim_type
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthkey import build_truthkey, parse_truthkey
from kaori_truth.trust_snapshot import AgentTrust, TrustSnapshot

ROOT = Path(__file__).resolve().parents[2] / "kaori-spec" / "schemas"
EVENT = datetime(2026, 9, 27, 8, 41, tzinfo=timezone.utc)
MALE = {"lat": 4.1755, "lon": 73.5093}


def _load():
    return load_claim_type(ROOT / "earth" / "flood_water_v1.yaml")


def test_flood_water_keeps_the_flood_rules_and_adds_the_claim():
    water = _load()
    flood = load_claim_type(ROOT / "earth" / "flood_v1.yaml")
    assert water.id == "earth.flood_water.v1"
    assert (water.domain, water.topic) == ("earth", "flood_water")
    assert water.risk_profile == flood.risk_profile == "critical"
    assert (water.truthkey.spatial_system, water.truthkey.resolution, water.truthkey.time_bucket) == ("h3", 8, "PT1H")
    assert water.minimum_observations() == flood.minimum_observations() == 3
    water.validate_domain_config()
    fields = [f["name"] for f in water.get_config()["ui_schema"]["fields"]]
    assert list(water.output_schema["properties"]) == fields
    assert water.output_schema["required"] == ["water_present", "extent"]
    assert "water_level_cm" not in water.output_schema["properties"]
    assert flood.output_schema is None


def test_flood_water_truthkey_is_the_hexagon_and_the_hour():
    water = _load()
    key = build_truthkey(
        claim_type_id=water.id,
        event_time=EVENT,
        location=MALE,
        spatial_system=water.truthkey.spatial_system,
        spatial_resolution=water.truthkey.resolution,
        z_index=water.truthkey.z_index,
        time_bucket_duration=water.truthkey.time_bucket,
    )
    assert key == "earth:flood_water:h3:886142a8e7fffff:surface:2026-09-27T08:00Z"
    assert parse_truthkey(key).topic == "flood_water"


def _observation(n: int, present: bool, extent: str) -> Observation:
    return Observation(
        observation_id=UUID(f"{n:08d}-1111-1111-1111-111111111111"),
        claim_type="earth.flood_water.v1",
        reported_at=EVENT,
        reporter_id=f"user:reporter-{n}",
        reporter_context=ReporterContext(standing=Standing.SILVER, trust_score=0.75, source_type="human"),
        geo=MALE,
        payload={"water_present": present, "extent": extent},
        evidence_refs=[EvidenceRef(uri=f"gs://kaori-evidence/flood-{n}.jpg", sha256=f"{n}" * 64)],
    )


def _trust(observations):
    return TrustSnapshot.create(
        snapshot_id="snapshot-flood-water",
        snapshot_time=EVENT,
        agent_trusts={
            o.reporter_id: AgentTrust(agent_id=o.reporter_id, effective_trust=150.0, standing=150.0, derived_class="silver", flags=[])
            for o in observations
        },
    )


def _compile(observations):
    water = _load()
    return compile_truth_state(
        claim_type=water,
        truth_key="earth:flood_water:h3:886142a8e7fffff:surface:2026-09-27T08:00Z",
        observations=observations,
        trust_snapshot=_trust(observations),
        policy_version=water.policy_version,
        compile_time=EVENT,
    )


def test_three_reports_compile_to_a_flood_claim_deterministically():
    observations = [_observation(1, True, "street"), _observation(2, True, "street"), _observation(3, True, "block")]
    first, second = _compile(observations), _compile(observations)
    assert first.claim == {"water_present": True, "extent": "street"}
    # critical: never verified without a human vote
    assert first.status.value != "VERIFIED_TRUE"
    assert first.security.semantic_hash == second.security.semantic_hash


def test_absence_is_a_claim_too():
    observations = [_observation(1, False, "none"), _observation(2, False, "none"), _observation(3, True, "patches")]
    state = _compile(observations)
    assert state.claim == {"water_present": False, "extent": "none"}
