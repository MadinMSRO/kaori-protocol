"""
Kaori Truth — Confidence Computation

Compute composite confidence from components (SPEC Section 11).
"""
from __future__ import annotations

from typing import Dict, Optional

from kaori_truth.primitives.truthstate import ConfidenceBreakdown


def compute_confidence(
    components: Dict[str, float],
    claim_config: dict,
    modifiers: Optional[Dict[str, bool]] = None,
) -> ConfidenceBreakdown:
    """
    Compute composite confidence from components using claim configuration.
    
    Formula: confidence = Σ(component_weight × component_value) + Σ(modifiers)
    
    Args:
        components: Dict mapping component names to values (0-1)
        claim_config: Claim configuration with confidence_model
        modifiers: Dict of active modifiers (e.g., {"contradiction_detected": True})
        
    Returns:
        ConfidenceBreakdown with component scores and final clamped score
    """
    confidence_config = claim_config.get("confidence_model", {})
    component_configs = confidence_config.get("components", {})
    modifier_configs = confidence_config.get("modifiers", {})
    
    modifiers = modifiers or {}
    
    # Calculate component contributions
    component_scores = {}
    raw_score = 0.0
    
    for comp_name, comp_config in component_configs.items():
        weight = comp_config.get("weight", 0.0) if isinstance(comp_config, dict) else 0.0
        value = components.get(comp_name, 0.0)
        contribution = weight * value
        component_scores[comp_name] = contribution
        raw_score += contribution
    
    # Default: just use AI confidence if no config
    if not component_scores and "ai_confidence" in components:
        raw_score = components["ai_confidence"]
        component_scores["ai_confidence"] = raw_score
    
    # Apply modifiers
    modifier_scores = {}
    
    for mod_name, mod_value in modifier_configs.items():
        if isinstance(mod_value, (int, float)):
            base_name = mod_name.replace("_penalty", "").replace("_bonus", "")
            if modifiers.get(base_name) or modifiers.get(f"{base_name}_detected"):
                modifier_scores[mod_name] = mod_value
                raw_score += mod_value
    
    # Clamp to [0.0, 1.0]
    final_score = max(0.0, min(1.0, raw_score))
    
    return ConfidenceBreakdown(
        components=component_scores,
        modifiers=modifier_scores,
        raw_score=raw_score,
        final_score=final_score,
    )


def get_confidence_level(confidence: float, claim_config: dict) -> str:
    """
    Get confidence level label (high/medium/low) based on thresholds.
    """
    confidence_config = claim_config.get("confidence_model", {})
    thresholds = confidence_config.get("thresholds", {})
    
    high = thresholds.get("high", 0.80)
    medium = thresholds.get("medium", 0.50)
    
    if confidence >= high:
        return "high"
    elif confidence >= medium:
        return "medium"
    else:
        return "low"
