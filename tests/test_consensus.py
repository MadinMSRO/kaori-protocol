"""Tests for consensus computation."""
import pytest
from datetime import datetime, timezone

from core.models import Standing, Vote, VoteType
from core.consensus import compute_consensus, get_consensus_outcome


class TestConsensusComputation:
    """Test weighted threshold consensus."""
    
    @pytest.fixture
    def claim_config(self):
        return {
            "consensus_model": {
                "type": "weighted_threshold",
                "finalize_threshold": 15,
                "reject_threshold": -10,
                "weighted_roles": {
                    "bronze": 1,
                    "silver": 3,
                    "expert": 7,
                    "ministry": 10,
                },
                "override_allowed_roles": ["ministry"],
                "vote_types": {
                    "RATIFY": 1,
                    "REJECT": -1,
                    "CHALLENGE": 0,
                    "OVERRIDE": "special",
                },
            }
        }
    
    def _make_vote(self, standing: Standing, vote_type: VoteType) -> Vote:
        return Vote(
            voter_id=f"voter_{standing.value}",
            voter_standing=standing,
            vote_type=vote_type,
            voted_at=datetime.now(timezone.utc),
        )
    
    def test_empty_votes(self, claim_config):
        result = compute_consensus([], claim_config)
        assert result.score == 0
        assert not result.finalized
    
    def test_bronze_votes_only(self, claim_config):
        votes = [
            self._make_vote(Standing.BRONZE, VoteType.RATIFY),
            self._make_vote(Standing.BRONZE, VoteType.RATIFY),
            self._make_vote(Standing.BRONZE, VoteType.RATIFY),
        ]
        result = compute_consensus(votes, claim_config)
        assert result.score == 3  # 3 × 1 × 1
        assert not result.finalized
    
    def test_expert_vote_weight(self, claim_config):
        votes = [
            self._make_vote(Standing.EXPERT, VoteType.RATIFY),
            self._make_vote(Standing.EXPERT, VoteType.RATIFY),
        ]
        result = compute_consensus(votes, claim_config)
        assert result.score == 14  # 2 × 7 × 1
        assert not result.finalized  # Just under threshold
    
    def test_finalize_threshold_reached(self, claim_config):
        votes = [
            self._make_vote(Standing.EXPERT, VoteType.RATIFY),
            self._make_vote(Standing.EXPERT, VoteType.RATIFY),
            self._make_vote(Standing.BRONZE, VoteType.RATIFY),
        ]
        result = compute_consensus(votes, claim_config)
        assert result.score == 15  # 2×7 + 1×1
        assert result.finalized
        assert "THRESHOLD_REACHED" in result.finalize_reason
    
    def test_reject_threshold_reached(self, claim_config):
        votes = [
            self._make_vote(Standing.EXPERT, VoteType.REJECT),
            self._make_vote(Standing.SILVER, VoteType.REJECT),
        ]
        result = compute_consensus(votes, claim_config)
        assert result.score == -10  # 7×(-1) + 3×(-1)
        assert result.finalized
        assert "REJECT_THRESHOLD" in result.finalize_reason
    
    def test_ministry_override(self, claim_config):
        votes = [
            self._make_vote(Standing.BRONZE, VoteType.REJECT),
            self._make_vote(Standing.MINISTRY, VoteType.OVERRIDE),
        ]
        result = compute_consensus(votes, claim_config)
        assert result.finalized
        assert "OVERRIDE" in result.finalize_reason
    
    def test_challenge_vote_no_score(self, claim_config):
        votes = [
            self._make_vote(Standing.EXPERT, VoteType.RATIFY),
            self._make_vote(Standing.SILVER, VoteType.CHALLENGE),
        ]
        result = compute_consensus(votes, claim_config)
        assert result.score == 7  # Challenge adds 0
    
    def test_positive_ratio(self, claim_config):
        votes = [
            self._make_vote(Standing.BRONZE, VoteType.RATIFY),
            self._make_vote(Standing.BRONZE, VoteType.RATIFY),
            self._make_vote(Standing.BRONZE, VoteType.REJECT),
        ]
        result = compute_consensus(votes, claim_config)
        # ratio = (2-1)/3 = 0.33, normalized = (0.33+1)/2 = 0.67
        assert 0.6 < result.positive_ratio < 0.7


class TestConsensusOutcome:
    """Test consensus outcome determination."""
    
    @pytest.fixture
    def claim_config(self):
        return {
            "consensus_model": {
                "finalize_threshold": 15,
                "reject_threshold": -10,
            }
        }
    
    def test_verified_true(self, claim_config):
        from core.models import ConsensusRecord
        consensus = ConsensusRecord(
            score=15,
            finalized=True,
            finalize_reason="THRESHOLD_REACHED",
        )
        outcome = get_consensus_outcome(consensus, claim_config)
        assert outcome == "VERIFIED_TRUE"
    
    def test_verified_false(self, claim_config):
        from core.models import ConsensusRecord
        consensus = ConsensusRecord(
            score=-10,
            finalized=True,
            finalize_reason="REJECT_THRESHOLD",
        )
        outcome = get_consensus_outcome(consensus, claim_config)
        assert outcome == "VERIFIED_FALSE"
    
    def test_not_finalized(self, claim_config):
        from core.models import ConsensusRecord
        consensus = ConsensusRecord(
            score=5,
            finalized=False,
        )
        outcome = get_consensus_outcome(consensus, claim_config)
        assert outcome is None
