"""
Kaori Truth — Test Suite for Determinism

Tests that verify the pure compiler produces identical output for identical inputs.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import UUID

from kaori_truth import (
    compile_truth_state,
    TrustSnapshot,
    AgentTrust,
    Observation,
    ClaimType,
    TruthKey,
)
from kaori_truth.primitives.observation import ReporterContext, Standing
from kaori_truth.primitives.evidence import EvidenceRef


def create_test_observation(
    observation_id: str = "11111111-1111-1111-1111-111111111111",
    reporter_id: str = "agent-001",
    reported_at: datetime = None,
) -> Observation:
    """Create a test observation with fixed values."""
    if reported_at is None:
        reported_at = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
    
    return Observation(
        observation_id=UUID(observation_id),
        claim_type="earth.flood.v1",
        reported_at=reported_at,
        reporter_id=reporter_id,
        reporter_context=ReporterContext(
            standing=Standing.SILVER,
            trust_score=0.75,
            source_type="human",
        ),
        geo={"lat": 4.175, "lon": 73.509},
        payload={"water_level": "1.5", "severity": "moderate"},  # Numeric string for derivation
        evidence_refs=[
            EvidenceRef(
                uri="gs://kaori-evidence/photo1.jpg",
                sha256="a" * 64,
            )
        ],
    )


def create_test_claim_type() -> ClaimType:
    """Create a test ClaimType."""
    return ClaimType(
        id="earth.flood.v1",
        version=1,
        domain="earth",
        topic="flood",
        risk_profile="monitor",

        output_schema={
            "type": "object",
            "properties": {
                "severity": {"type": "string"},
                "water_level_meters": {"type": "number"},
                "observation_count": {"type": "integer"},
                "network_trust": {"type": "number"},
            }
        }
    )


# Removed create_test_claim_payload as it's no longer used


def create_test_trust_snapshot(
    agent_ids: list[str],
    snapshot_time: datetime,
) -> TrustSnapshot:
    """Create a test TrustSnapshot with fixed values."""
    agent_trusts = {}
    for agent_id in agent_ids:
        agent_trusts[agent_id] = AgentTrust(
            agent_id=agent_id,
            effective_power=150.0,
            standing=150.0,
            derived_class="silver",
            flags=[],
        )
    return TrustSnapshot.create(
        snapshot_id="snapshot-001",
        snapshot_time=snapshot_time,
        agent_trusts=agent_trusts,
    )


class TestDeterministicCompilation:
    """Tests for deterministic compilation."""
    
    def test_same_inputs_produce_identical_semantic_hash(self):
        """
        Same inputs MUST produce identical semantic_hash.
        
        This is the core determinism guarantee.
        """
        # Setup
        compile_time = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        observation = create_test_observation()
        claim_type = create_test_claim_type()
        truth_key = "earth:flood:h3:886142a8e7fffff:surface:2026-01-07T12:00Z"
        trust_snapshot = create_test_trust_snapshot(
            ["agent-001"],
            compile_time,
        )
        
        # Compile twice
        state1 = compile_truth_state(
            claim_type=claim_type,
            truth_key=truth_key,
            observations=[observation],
            trust_snapshot=trust_snapshot,
            policy_version="earth.flood.v1.policy.1",
            compiler_version="1.0.0",
            compile_time=compile_time,
        )
        
        state2 = compile_truth_state(
            claim_type=claim_type,
            truth_key=truth_key,
            observations=[observation],
            trust_snapshot=trust_snapshot,
            policy_version="earth.flood.v1.policy.1",
            compiler_version="1.0.0",
            compile_time=compile_time,
        )
        
        # semantic_hash MUST be identical
        assert state1.security.semantic_hash == state2.security.semantic_hash
        
        # state_hash MUST also be identical (same compile_time)
        assert state1.security.state_hash == state2.security.state_hash
    
    def test_different_compile_time_same_semantic_hash(self):
        """
        Different compile_time should produce:
        - SAME semantic_hash (content unchanged)
        - DIFFERENT state_hash (envelope changed)
        """
        observation = create_test_observation()
        claim_type = create_test_claim_type()
        truth_key = "earth:flood:h3:886142a8e7fffff:surface:2026-01-07T12:00Z"
        
        # Same trust snapshot time (important!)
        snapshot_time = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        trust_snapshot = create_test_trust_snapshot(["agent-001"], snapshot_time)
        
        # Compile at different times
        compile_time_1 = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        compile_time_2 = datetime(2026, 1, 7, 12, 5, 0, tzinfo=timezone.utc)  # 5 min later
        
        state1 = compile_truth_state(
            claim_type=claim_type,
            truth_key=truth_key,
            observations=[observation],
            trust_snapshot=trust_snapshot,
            policy_version="earth.flood.v1.policy.1",
            compiler_version="1.0.0",
            compile_time=compile_time_1,
        )
        
        state2 = compile_truth_state(
            claim_type=claim_type,
            truth_key=truth_key,
            observations=[observation],
            trust_snapshot=trust_snapshot,
            policy_version="earth.flood.v1.policy.1",
            compiler_version="1.0.0",
            compile_time=compile_time_2,
        )
        
        # semantic_hash MUST be identical (content is same)
        assert state1.security.semantic_hash == state2.security.semantic_hash
        
        # state_hash MUST be different (compile_time differs)
        assert state1.security.state_hash != state2.security.state_hash
    
    def test_compile_time_required(self):
        """Compilation MUST fail if compile_time is not provided."""
        observation = create_test_observation()
        claim_type = create_test_claim_type()
        truth_key = "earth:flood:h3:886142a8e7fffff:surface:2026-01-07T12:00Z"
        trust_snapshot = create_test_trust_snapshot(
            ["agent-001"],
            datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc),
        )
        
        with pytest.raises(Exception) as exc_info:
            compile_truth_state(
                claim_type=claim_type,
                truth_key=truth_key,
                observations=[observation],
                trust_snapshot=trust_snapshot,
                policy_version="earth.flood.v1.policy.1",
                compile_time=None,  # Not provided
            )
        
        assert "compile_time" in str(exc_info.value).lower()


class TestCanonicalHashing:
    """Tests for canonical hashing."""
    
    def test_observation_hash_deterministic(self):
        """Same observation produces identical hash."""
        obs1 = create_test_observation()
        obs2 = create_test_observation()
        
        assert obs1.hash() == obs2.hash()
    
    def test_claimtype_hash_deterministic(self):
        """Same ClaimType produces identical hash."""
        ct1 = create_test_claim_type()
        ct2 = create_test_claim_type()
        
        assert ct1.hash() == ct2.hash()
    
    def test_trust_snapshot_hash_deterministic(self):
        """Same TrustSnapshot produces identical hash."""
        time = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        
        snap1 = create_test_trust_snapshot(["agent-001"], time)
        snap2 = create_test_trust_snapshot(["agent-001"], time)
        
        assert snap1.snapshot_hash == snap2.snapshot_hash
    
    def test_evidence_ref_hash_deterministic(self):
        """EvidenceRef with same content produces identical hash."""
        ref1 = EvidenceRef(
            uri="gs://bucket/file.jpg",
            sha256="a" * 64,
        )
        ref2 = EvidenceRef(
            uri="gs://bucket/file.jpg",
            sha256="a" * 64,
        )
        
        assert ref1.hash() == ref2.hash()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
