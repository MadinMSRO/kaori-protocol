"""Tests for confidence computation."""
import pytest

from core.confidence import compute_confidence, get_confidence_level, should_flag_low_confidence


class TestConfidenceComputation:
    """Test composite confidence calculation."""
    
    @pytest.fixture
    def claim_config(self):
        return {
            "confidence_model": {
                "type": "composite",
                "components": {
                    "ai_confidence": {
                        "weight": 0.40,
                        "source": "ai_validation.confidence",
                    },
                    "consensus_ratio": {
                        "weight": 0.30,
                        "source": "consensus.positive_ratio",
                    },
                    "evidence_count": {
                        "weight": 0.20,
                        "source": "evidence.count",
                        "normalize": {
                            "min": 1,
                            "max": 5,
                        },
                    },
                    "reporter_trust": {
                        "weight": 0.10,
                        "source": "reporter_context.trust_score",
                    },
                },
                "modifiers": {
                    "contradiction_penalty": -0.20,
                    "expert_bonus": 0.05,
                },
                "thresholds": {
                    "high": 0.80,
                    "medium": 0.50,
                    "low": 0.30,
                },
            },
        }
    
    def test_basic_computation(self, claim_config):
        components = {
            "ai_confidence": 0.85,
            "consensus_ratio": 0.70,
            "evidence_count": 3,  # Will be normalized
            "reporter_trust": 0.60,
        }
        
        result = compute_confidence(components, claim_config)
        
        # ai: 0.40 × 0.85 = 0.34
        # consensus: 0.30 × 0.70 = 0.21
        # evidence: 0.20 × 0.5 (normalized: (3-1)/(5-1) = 0.5) = 0.10
        # trust: 0.10 × 0.60 = 0.06
        # Total: 0.71
        assert 0.70 < result.final_score < 0.72
    
    def test_clamping_to_one(self, claim_config):
        components = {
            "ai_confidence": 1.0,
            "consensus_ratio": 1.0,
            "evidence_count": 5,
            "reporter_trust": 1.0,
        }
        
        result = compute_confidence(components, claim_config)
        assert result.final_score <= 1.0
    
    def test_clamping_to_zero(self, claim_config):
        components = {
            "ai_confidence": 0.0,
            "consensus_ratio": 0.0,
            "evidence_count": 1,
            "reporter_trust": 0.0,
        }
        modifiers = {"contradiction_detected": True}
        
        result = compute_confidence(components, claim_config, modifiers)
        assert result.final_score >= 0.0
    
    def test_contradiction_penalty(self, claim_config):
        components = {
            "ai_confidence": 0.80,
            "consensus_ratio": 0.70,
            "evidence_count": 3,
            "reporter_trust": 0.60,
        }
        
        without_mod = compute_confidence(components, claim_config)
        with_mod = compute_confidence(
            components, 
            claim_config, 
            {"contradiction_detected": True}
        )
        
        # Penalty should reduce score
        assert with_mod.final_score < without_mod.final_score
        assert "contradiction_penalty" in with_mod.modifiers
    
    def test_missing_components(self, claim_config):
        # Only provide some components
        components = {
            "ai_confidence": 0.85,
        }
        
        result = compute_confidence(components, claim_config)
        # Should still compute without error
        assert 0.0 <= result.final_score <= 1.0


class TestConfidenceLevel:
    """Test confidence level classification."""
    
    @pytest.fixture
    def claim_config(self):
        return {
            "confidence_model": {
                "thresholds": {
                    "high": 0.80,
                    "medium": 0.50,
                },
            },
        }
    
    def test_high_confidence(self, claim_config):
        assert get_confidence_level(0.85, claim_config) == "high"
        assert get_confidence_level(0.80, claim_config) == "high"
    
    def test_medium_confidence(self, claim_config):
        assert get_confidence_level(0.65, claim_config) == "medium"
        assert get_confidence_level(0.50, claim_config) == "medium"
    
    def test_low_confidence(self, claim_config):
        assert get_confidence_level(0.30, claim_config) == "low"
        assert get_confidence_level(0.0, claim_config) == "low"


class TestLowConfidenceFlag:
    """Test low confidence flagging."""
    
    @pytest.fixture
    def claim_config(self):
        return {
            "state_verification_policy": {
                "monitor_lane": {
                    "transparency_flag_if_composite_below": 0.82,
                    "flag_label": "LOW_COMPOSITE_CONFIDENCE",
                },
            },
        }
    
    def test_should_flag_below_threshold(self, claim_config):
        should_flag, label = should_flag_low_confidence(0.75, claim_config, "monitor")
        assert should_flag is True
        assert label == "LOW_COMPOSITE_CONFIDENCE"
    
    def test_should_not_flag_above_threshold(self, claim_config):
        should_flag, label = should_flag_low_confidence(0.85, claim_config, "monitor")
        assert should_flag is False
        assert label is None
    
    def test_critical_lane_no_flag(self, claim_config):
        should_flag, label = should_flag_low_confidence(0.50, claim_config, "critical")
        assert should_flag is False
