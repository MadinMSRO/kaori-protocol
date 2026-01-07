"""
Kaori Core — Confidence Computation

Compute composite confidence from components (SPEC Section 11).
"""
from __future__ import annotations

from .models import ConfidenceBreakdown


def compute_confidence(
    components: dict[str, float],
    claim_config: dict,
    modifiers: dict[str, bool] | None = None,
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
        weight = comp_config.get("weight", 0.0)
        
        # Get the value from provided components
        value = components.get(comp_name, 0.0)
        
        # Apply normalization if specified
        normalize = comp_config.get("normalize", None)
        if normalize and isinstance(value, (int, float)):
            min_val = normalize.get("min", 0)
            max_val = normalize.get("max", 1)
            if max_val > min_val:
                value = (value - min_val) / (max_val - min_val)
                value = max(0.0, min(1.0, value))
        
        contribution = weight * value
        component_scores[comp_name] = contribution
        raw_score += contribution
    
    # Apply modifiers
    modifier_scores = {}
    
    for mod_name, mod_config in modifier_configs.items():
        if isinstance(mod_config, dict):
            # Complex modifier with condition
            condition = mod_config.get("condition", "")
            apply_value = mod_config.get("apply", "0")
            
            # Check if condition is met
            condition_met = False
            if "contradiction_detected" in condition and modifiers.get("contradiction_detected"):
                condition_met = True
            elif modifiers.get(mod_name):
                condition_met = True
            
            if condition_met:
                # Parse apply value
                if isinstance(apply_value, str):
                    apply_value = float(apply_value)
                modifier_scores[mod_name] = apply_value
                raw_score += apply_value
        else:
            # Simple modifier value
            if modifiers.get(mod_name.replace("_penalty", "").replace("_bonus", "")):
                value = float(mod_config) if isinstance(mod_config, str) else mod_config
                modifier_scores[mod_name] = value
                raw_score += value
    
    # Handle simple modifier format (e.g., "contradiction_penalty": -0.20)
    if not modifier_scores:
        for mod_name, mod_value in modifier_configs.items():
            if isinstance(mod_value, (int, float)):
                # Check if related modifier is active
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
    
    Args:
        confidence: Composite confidence score (0-1)
        claim_config: Claim configuration with thresholds
        
    Returns:
        "high", "medium", or "low"
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


def should_flag_low_confidence(
    confidence: float,
    claim_config: dict,
    risk_profile: str = "monitor",
) -> tuple[bool, str | None]:
    """
    Check if truth state should be flagged for low confidence.
    
    Args:
        confidence: Composite confidence score
        claim_config: Claim configuration
        risk_profile: "monitor" or "critical"
        
    Returns:
        Tuple of (should_flag, flag_label)
    """
    policy = claim_config.get("state_verification_policy", {})
    
    if risk_profile == "monitor":
        lane_config = policy.get("monitor_lane", {})
        threshold = lane_config.get("transparency_flag_if_composite_below", 0.82)
        label = lane_config.get("flag_label", "LOW_COMPOSITE_CONFIDENCE")
        
        if confidence < threshold:
            return True, label
    
    return False, None
