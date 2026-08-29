"""
Schema-driven TruthState.claim derivation.

Claim keys come only from ClaimType.output_schema properties.
Missing output_schema fails compile. No ui_schema fallback.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from kaori_truth import CompilationError, compile_truth_state
from kaori_truth.claim_derivation import ClaimDerivationError, derive_claim_payload
from kaori_truth.factory import load_claim_type
from kaori_truth.primitives.claimtype import ClaimType
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.trust_snapshot import AgentTrust, TrustSnapshot

SCHEMAS = Path(__file__).resolve().parents[2] / "kaori-spec" / "schemas"
COMPILE_TIME = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)


def _observation(
    *,
    observation_id: str = "11111111-1111-1111-1111-111111111111",
    reporter_id: str = "agent-001",
    claim_type: str = "ocean.coral_bleaching.v1",
    payload: dict,
) -> Observation:
    return Observation(
        observation_id=UUID(observation_id),
        claim_type=claim_type,
        reported_at=COMPILE_TIME,
        reporter_id=reporter_id,
        reporter_context=ReporterContext(
            standing=Standing.SILVER,
            trust_score=0.75,
            source_type="human",
        ),
        geo={"lat": -8.3405, "lon": 115.0920},
        payload=payload,
        evidence_refs=[
            EvidenceRef(uri="gs://kaori-evidence/a.jpg", sha256="a" * 64),
        ],
    )


def _trust(*agent_ids: str, power: float = 150.0) -> TrustSnapshot:
    return TrustSnapshot.create(
        snapshot_id="snapshot-001",
        snapshot_time=COMPILE_TIME,
        agent_trusts={
            agent_id: AgentTrust(
                agent_id=agent_id,
                effective_trust=power,
                standing=power,
                derived_class="silver",
                flags=[],
            )
            for agent_id in agent_ids
        },
    )


def _claim_type(*, output_schema: dict | None, topic: str = "coral_bleaching") -> ClaimType:
    return ClaimType(
        id=f"ocean.{topic}.v1",
        version=1,
        domain="ocean",
        topic=topic,
        output_schema=output_schema,
    )


CORAL_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["bleaching_present", "bleaching_percentage"],
    "properties": {
        "bleaching_present": {"type": "boolean"},
        "bleaching_percentage": {"type": "number", "minimum": 0, "maximum": 100},
    },
}


class TestDeriveClaimPayloadSchemaDriven:
    def test_coral_declaration_and_extent_from_output_schema(self):
        claim_type = _claim_type(output_schema=CORAL_OUTPUT_SCHEMA)
        observations = [
            _observation(
                payload={
                    "depth_meters": 8.0,
                    "bleaching_present": True,
                    "bleaching_percentage": 40,
                }
            )
        ]
        claim = derive_claim_payload(
            observations, _trust("agent-001"), claim_type, "ocean:coral_bleaching:h3:x:underwater:2026-01-07T00:00Z"
        )
        assert claim == {
            "bleaching_percentage": 40,
            "bleaching_present": True,
        }
        assert "depth_meters" not in claim
        assert "severity" not in claim
        assert "network_trust" not in claim
        assert "observation_count" not in claim

    def test_missing_output_schema_fails(self):
        claim_type = _claim_type(output_schema=None)
        with pytest.raises(ClaimDerivationError, match="missing output_schema"):
            derive_claim_payload(
                [_observation(payload={"bleaching_percentage": 40})],
                _trust("agent-001"),
                claim_type,
                "ocean:coral_bleaching:h3:x:underwater:2026-01-07T00:00Z",
            )

    def test_does_not_guess_severity_when_schema_absent(self):
        claim_type = _claim_type(output_schema=None, topic="unknown")
        with pytest.raises(ClaimDerivationError, match="missing output_schema"):
            derive_claim_payload(
                [_observation(payload={"severity": "high", "water_level": 1.2})],
                _trust("agent-001"),
                claim_type,
                "earth:flood:h3:x:surface:2026-01-07T12:00Z",
            )

    def test_power_weighted_number_average(self):
        claim_type = _claim_type(
            output_schema={
                "type": "object",
                "properties": {"bleaching_percentage": {"type": "number"}},
            }
        )
        observations = [
            _observation(
                observation_id="11111111-1111-1111-1111-111111111111",
                reporter_id="agent-a",
                payload={"bleaching_percentage": 20},
            ),
            _observation(
                observation_id="22222222-2222-2222-2222-222222222222",
                reporter_id="agent-b",
                payload={"bleaching_percentage": 80},
            ),
        ]
        trust = TrustSnapshot.create(
            snapshot_id="snapshot-001",
            snapshot_time=COMPILE_TIME,
            agent_trusts={
                "agent-a": AgentTrust(
                    agent_id="agent-a",
                    effective_trust=100.0,
                    standing=100.0,
                    derived_class="bronze",
                    flags=[],
                ),
                "agent-b": AgentTrust(
                    agent_id="agent-b",
                    effective_trust=300.0,
                    standing=300.0,
                    derived_class="silver",
                    flags=[],
                ),
            },
        )
        claim = derive_claim_payload(
            observations, trust, claim_type, "ocean:coral_bleaching:h3:x:underwater:2026-01-07T00:00Z"
        )
        assert claim["bleaching_percentage"] == pytest.approx(65.0)

    def test_boolean_consensus(self):
        claim_type = _claim_type(
            output_schema={
                "type": "object",
                "properties": {"bleaching_present": {"type": "boolean"}},
            }
        )
        observations = [
            _observation(
                observation_id="11111111-1111-1111-1111-111111111111",
                reporter_id="agent-a",
                payload={"bleaching_present": False},
            ),
            _observation(
                observation_id="22222222-2222-2222-2222-222222222222",
                reporter_id="agent-b",
                payload={"bleaching_present": True},
            ),
        ]
        trust = TrustSnapshot.create(
            snapshot_id="snapshot-001",
            snapshot_time=COMPILE_TIME,
            agent_trusts={
                "agent-a": AgentTrust(
                    agent_id="agent-a",
                    effective_trust=10.0,
                    standing=10.0,
                    derived_class="bronze",
                    flags=[],
                ),
                "agent-b": AgentTrust(
                    agent_id="agent-b",
                    effective_trust=90.0,
                    standing=90.0,
                    derived_class="expert",
                    flags=[],
                ),
            },
        )
        claim = derive_claim_payload(
            observations, trust, claim_type, "ocean:coral_bleaching:h3:x:underwater:2026-01-07T00:00Z"
        )
        assert claim["bleaching_present"] is True

    def test_array_highest_power_wins(self):
        claim_type = ClaimType(
            id="earth.coastal_erosion.v1",
            version=1,
            domain="earth",
            topic="coastal_erosion",
            output_schema={
                "type": "object",
                "properties": {"stake_readings": {"type": "array"}},
            },
        )
        observations = [
            _observation(
                observation_id="11111111-1111-1111-1111-111111111111",
                reporter_id="agent-a",
                claim_type="earth.coastal_erosion.v1",
                payload={"stake_readings": [0.1]},
            ),
            _observation(
                observation_id="22222222-2222-2222-2222-222222222222",
                reporter_id="agent-b",
                claim_type="earth.coastal_erosion.v1",
                payload={"stake_readings": [0.9, 1.0]},
            ),
        ]
        trust = TrustSnapshot.create(
            snapshot_id="snapshot-001",
            snapshot_time=COMPILE_TIME,
            agent_trusts={
                "agent-a": AgentTrust(
                    agent_id="agent-a",
                    effective_trust=10.0,
                    standing=10.0,
                    derived_class="bronze",
                    flags=[],
                ),
                "agent-b": AgentTrust(
                    agent_id="agent-b",
                    effective_trust=50.0,
                    standing=50.0,
                    derived_class="silver",
                    flags=[],
                ),
            },
        )
        claim = derive_claim_payload(
            observations, trust, claim_type, "earth:coastal_erosion:h3:x:surface:2026-01-07T00:00Z"
        )
        assert claim["stake_readings"] == [0.9, 1.0]


class TestCompileClaimFromOutputSchema:
    def test_coral_compile_puts_declaration_and_extent_on_claim(self):
        claim_type = load_claim_type(SCHEMAS / "ocean" / "coral_bleaching_v1.yaml")
        assert claim_type.output_schema is not None
        assert set(claim_type.output_schema["properties"]) == {
            "bleaching_present",
            "bleaching_percentage",
        }

        state = compile_truth_state(
            claim_type=claim_type,
            truth_key="ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z",
            observations=[
                _observation(
                    payload={
                        "depth_meters": 8.0,
                        "bleaching_present": True,
                        "bleaching_percentage": 40,
                    }
                )
            ],
            trust_snapshot=_trust("agent-001"),
            policy_version=claim_type.policy_version,
            compile_time=COMPILE_TIME,
        )
        assert state.claim["bleaching_present"] is True
        assert state.claim["bleaching_percentage"] == 40
        assert "depth_meters" not in state.claim
        assert "severity" not in state.claim
        assert "network_trust" not in state.claim
        assert "confidence" not in state.claim

    def test_coral_missing_required_output_field_fails_compile(self):
        claim_type = load_claim_type(SCHEMAS / "ocean" / "coral_bleaching_v1.yaml")
        with pytest.raises(CompilationError, match="REQUIRED"):
            compile_truth_state(
                claim_type=claim_type,
                truth_key="ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z",
                observations=[
                    _observation(
                        payload={"depth_meters": 8.0, "bleaching_percentage": 40}
                    )
                ],
                trust_snapshot=_trust("agent-001"),
                policy_version=claim_type.policy_version,
                compile_time=COMPILE_TIME,
            )

    def test_earth_liminal_type_keeps_output_schema_keys(self):
        claim_type = load_claim_type(SCHEMAS / "earth" / "coastal_erosion_v1.yaml")
        payload = {
            "recession_m": 1.5,
            "scarp_present": True,
            "stake_readings": [0.1, 0.2],
        }
        state = compile_truth_state(
            claim_type=claim_type,
            truth_key="earth:coastal_erosion:h3:abc:surface:2026-01-07T00:00Z",
            observations=[
                _observation(
                    claim_type="earth.coastal_erosion.v1",
                    payload=payload,
                )
            ],
            trust_snapshot=_trust("agent-001"),
            policy_version=claim_type.policy_version,
            compile_time=COMPILE_TIME,
        )
        assert state.claim["recession_m"] == 1.5
        assert state.claim["scarp_present"] is True
        assert state.claim["stake_readings"] == [0.1, 0.2]
        assert "severity" not in state.claim
        assert "network_trust" not in state.claim

    def test_space_liminal_type_keeps_output_schema_keys(self):
        claim_type = load_claim_type(SCHEMAS / "space" / "light_pollution_v1.yaml")
        payload = {"sky_quality": "poor", "sqm_value": 18.5, "weather": "clear"}
        state = compile_truth_state(
            claim_type=claim_type,
            truth_key="space:light_pollution:h3:abc:surface:2026-01-07T12:00Z",
            observations=[
                _observation(
                    claim_type="space.light_pollution.v1",
                    payload=payload,
                )
            ],
            trust_snapshot=_trust("agent-001"),
            policy_version=claim_type.policy_version,
            compile_time=COMPILE_TIME,
        )
        assert state.claim["sky_quality"] == "poor"
        assert state.claim["sqm_value"] == 18.5
        assert state.claim["weather"] == "clear"
        assert "severity" not in state.claim
        assert "network_trust" not in state.claim

    def test_open_core_flood_without_output_schema_fails_compile(self):
        claim_type = load_claim_type(SCHEMAS / "earth" / "flood_v1.yaml")
        assert claim_type.output_schema is None
        with pytest.raises(CompilationError, match="missing output_schema"):
            compile_truth_state(
                claim_type=claim_type,
                truth_key="earth:flood:h3:abc:surface:2026-01-07T12:00Z",
                observations=[
                    _observation(
                        claim_type="earth.flood.v1",
                        payload={"water_level_cm": 12, "severity": "high"},
                    )
                ],
                trust_snapshot=_trust("agent-001"),
                policy_version=claim_type.policy_version,
                compile_time=COMPILE_TIME,
            )

    def test_fixture_without_output_schema_fails_compile(self):
        claim_type = _claim_type(output_schema=None)
        with pytest.raises(CompilationError, match="missing output_schema"):
            compile_truth_state(
                claim_type=claim_type,
                truth_key="ocean:coral_bleaching:h3:x:underwater:2026-01-07T00:00Z",
                observations=[
                    _observation(
                        payload={"bleaching_present": True, "bleaching_percentage": 40}
                    )
                ],
                trust_snapshot=_trust("agent-001"),
                policy_version=claim_type.policy_version,
                compile_time=COMPILE_TIME,
            )
