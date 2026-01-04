"""Tests for the Kaori Engine."""
import pytest
from datetime import datetime, timezone

from core import (
    KaoriEngine,
    Observation,
    ReporterContext,
    Standing,
    TruthStatus,
    Vote,
    VoteType,
    AIValidationResult,
)


class TestEngineObservationProcessing:
    """Test observation processing through the engine."""
    
    @pytest.fixture
    def engine(self):
        return KaoriEngine(auto_sign=True)
    
    @pytest.fixture
    def observation(self):
        return Observation(
            claim_type="earth.flood.v1",
            reported_at=datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc),
            reporter_id="user123",
            reporter_context=ReporterContext(
                standing=Standing.BRONZE,
                trust_score=0.5,
            ),
            geo={"lat": 4.175, "lon": 73.509},
            payload={"water_level_cm": 150},
            evidence_refs=["gs://kaori-evidence/photo1.jpg"],
        )
    
    def test_process_observation_creates_truth_state(self, engine, observation):
        truth_state = engine.process_observation(observation)
        
        assert truth_state is not None
        assert truth_state.claim_type == "earth.flood.v1"
        assert truth_state.truthkey is not None
        assert observation.observation_id in truth_state.observation_ids
    
    def test_process_observation_with_ai_result(self, engine, observation):
        ai_result = AIValidationResult(
            bouncer_passed=True,
            generalist_confidence=0.85,
            final_confidence=0.85,
        )
        
        truth_state = engine.process_observation(observation, ai_result)
        
        assert truth_state.ai_confidence == 0.85
        assert truth_state.ai_validation is not None
    
    def test_truth_state_is_signed(self, engine, observation):
        truth_state = engine.process_observation(observation)
        
        assert truth_state.security is not None
        assert truth_state.security.truth_hash is not None
        assert truth_state.security.truth_signature is not None
    
    def test_multiple_observations_same_truthkey(self, engine, observation):
        # Process first observation
        ts1 = engine.process_observation(observation)
        truthkey_str = ts1.truthkey.to_string()
        
        # Process second observation with same location/time
        observation2 = Observation(
            claim_type="earth.flood.v1",
            reported_at=datetime(2026, 1, 2, 14, 45, 0, tzinfo=timezone.utc),  # Same hour
            reporter_id="user456",
            reporter_context=ReporterContext(
                standing=Standing.SILVER,
                trust_score=0.6,
            ),
            geo={"lat": 4.175, "lon": 73.509},  # Same location
            evidence_refs=["gs://kaori-evidence/photo2.jpg"],
        )
        
        ts2 = engine.process_observation(observation2)
        
        # Should be same truth key
        assert ts2.truthkey.to_string() == truthkey_str
        # Should have both observations
        assert len(ts2.observation_ids) == 2


class TestEngineVoting:
    """Test voting and consensus in the engine."""
    
    @pytest.fixture
    def engine(self):
        return KaoriEngine(auto_sign=True)
    
    @pytest.fixture
    def observation(self):
        return Observation(
            claim_type="earth.flood.v1",
            reported_at=datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc),
            reporter_id="user123",
            reporter_context=ReporterContext(
                standing=Standing.BRONZE,
                trust_score=0.5,
            ),
            geo={"lat": 4.175, "lon": 73.509},
        )
    
    def _make_vote(self, standing: float, vote_type: VoteType) -> Vote:
        return Vote(
            voter_id=f"voter_{standing}",
            voter_standing=standing,
            vote_type=vote_type,
            voted_at=datetime.now(timezone.utc),
        )
    
    def test_apply_vote(self, engine, observation):
        # First process observation
        ts = engine.process_observation(observation)
        truthkey = ts.truthkey
        
        # Apply vote with continuous standing
        vote = self._make_vote(200.0, VoteType.RATIFY)  # Expert-level standing
        ts = engine.apply_vote(truthkey, vote)
        
        assert ts.consensus is not None
        assert len(ts.consensus.votes) == 1
        assert ts.consensus.score >= 5  # weight(200) ≈ 5.4
    
    def test_votes_reach_threshold(self, engine, observation):
        ts = engine.process_observation(observation)
        truthkey = ts.truthkey
        
        # Apply enough votes to reach threshold (15)
        ts = engine.apply_vote(truthkey, self._make_vote(200.0, VoteType.RATIFY))  # Expert
        ts = engine.apply_vote(truthkey, self._make_vote(200.0, VoteType.RATIFY))  # Expert
        ts = engine.apply_vote(truthkey, self._make_vote(200.0, VoteType.RATIFY))  # Expert
        
        # Score should be >= 15 with 3 experts
        assert ts.consensus.score >= 15
        assert ts.consensus.finalized is True
        assert ts.status == TruthStatus.VERIFIED_TRUE
    
    def test_authority_override(self, engine, observation):
        ts = engine.process_observation(observation)
        truthkey = ts.truthkey
        
        # Single authority override should finalize
        ts = engine.apply_vote(truthkey, self._make_vote(500.0, VoteType.OVERRIDE))  # Authority
        
        assert ts.consensus.finalized is True
        assert ts.status == TruthStatus.VERIFIED_TRUE


class TestEngineRetrieval:
    """Test truth state retrieval."""
    
    @pytest.fixture
    def engine(self):
        return KaoriEngine(auto_sign=True)
    
    def test_get_truth_state(self, engine):
        observation = Observation(
            claim_type="earth.flood.v1",
            reported_at=datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc),
            reporter_id="user123",
            reporter_context=ReporterContext(
                standing=Standing.BRONZE,
                trust_score=0.5,
            ),
            geo={"lat": 4.175, "lon": 73.509},
        )
        
        ts = engine.process_observation(observation)
        
        # Retrieve by TruthKey object
        retrieved = engine.get_truth_state(ts.truthkey)
        assert retrieved is not None
        assert retrieved.claim_type == ts.claim_type
        
        # Retrieve by string
        retrieved = engine.get_truth_state(ts.truthkey.to_string())
        assert retrieved is not None
    
    def test_get_nonexistent_truth_state(self, engine):
        result = engine.get_truth_state("earth:flood:h3:nonexistent:surface:2026-01-01T00:00Z")
        assert result is None
