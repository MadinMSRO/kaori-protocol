"""
Kaori Core — Timeout Handler

Background job to handle stale truth states that haven't reached consensus.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
import re

from core.db.database import SessionLocal
from core.db import crud, models
from core.models import TruthStatus, VerificationBasis
from core.schema_loader import get_claim_type


def parse_iso_duration(duration_str: str) -> timedelta:
    """
    Parse ISO 8601 duration string to timedelta.
    
    Supports: PT12H, PT24H, PT48H, P1D, etc.
    """
    # Simple parser for common durations
    match = re.match(r'^PT?(\d+)([HDMS])$', duration_str.upper())
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        if unit == 'H':
            return timedelta(hours=value)
        elif unit == 'D':
            return timedelta(days=value)
        elif unit == 'M':
            return timedelta(minutes=value)
        elif unit == 'S':
            return timedelta(seconds=value)
    
    # Handle P1D format
    match = re.match(r'^P(\d+)D$', duration_str.upper())
    if match:
        return timedelta(days=int(match.group(1)))
    
    # Default fallback: 24 hours
    return timedelta(hours=24)


def process_stale_reviews(dry_run: bool = False) -> dict:
    """
    Process truth states that have been in PENDING_HUMAN_REVIEW 
    longer than the configured timeout.
    
    Args:
        dry_run: If True, don't actually update states, just report
        
    Returns:
        Summary of processed states
    """
    results = {
        "checked": 0,
        "transitioned_inconclusive": 0,
        "transitioned_expired": 0,
        "errors": [],
    }
    
    now = datetime.now(timezone.utc)
    
    with SessionLocal() as db:
        # Get all states in PENDING_HUMAN_REVIEW or INVESTIGATING
        pending_states = db.query(models.TruthStateModel).filter(
            models.TruthStateModel.status.in_([
                TruthStatus.PENDING_HUMAN_REVIEW.value,
                TruthStatus.INVESTIGATING.value,
            ])
        ).all()
        
        for state in pending_states:
            results["checked"] += 1
            
            try:
                # Get claim type config
                data = state.data or {}
                claim_type_id = data.get("claim_type", "")
                
                if not claim_type_id:
                    continue
                    
                claim_type = get_claim_type(claim_type_id)
                
                # Get timeout config
                dispute_config = claim_type.dispute_resolution
                temporal_config = claim_type.temporal_decay
                
                # Default timeout: 24 hours for peer review
                review_timeout = timedelta(hours=24)
                if dispute_config and dispute_config.timeout:
                    timeout_str = dispute_config.timeout.get("peer_review", "PT24H")
                    review_timeout = parse_iso_duration(timeout_str)
                
                # Check max validity (temporal expiry)
                max_validity = timedelta(days=1)
                if temporal_config:
                    max_validity = parse_iso_duration(temporal_config.max_validity)
                
                # Calculate age
                age = now - state.updated_at
                created_age = now - state.created_at
                
                # Check if expired (past max validity from creation)
                if created_age > max_validity:
                    if not dry_run:
                        state.status = TruthStatus.EXPIRED.value
                        state.verification_basis = VerificationBasis.TIMEOUT_DEFAULT.value
                        state.updated_at = now
                        db.add(state)
                    results["transitioned_expired"] += 1
                    continue
                
                # Check if stale (past review timeout from last update)
                if age > review_timeout:
                    if not dry_run:
                        state.status = TruthStatus.INCONCLUSIVE.value
                        state.verification_basis = VerificationBasis.TIMEOUT_INCONCLUSIVE.value
                        state.updated_at = now
                        # Add transparency flag
                        if state.data:
                            flags = state.data.get("transparency_flags", [])
                            if "REVIEW_TIMEOUT" not in flags:
                                flags.append("REVIEW_TIMEOUT")
                                state.data["transparency_flags"] = flags
                        db.add(state)
                    results["transitioned_inconclusive"] += 1
                    
            except Exception as e:
                results["errors"].append(f"{state.truthkey}: {str(e)}")
        
        if not dry_run:
            db.commit()
    
    return results


def run_timeout_check():
    """
    CLI entry point for timeout handling.
    """
    print("=== Kaori Timeout Handler ===\n")
    
    # First do a dry run
    print("Checking for stale reviews...")
    dry_results = process_stale_reviews(dry_run=True)
    
    print(f"  States checked: {dry_results['checked']}")
    print(f"  Would transition to INCONCLUSIVE: {dry_results['transitioned_inconclusive']}")
    print(f"  Would transition to EXPIRED: {dry_results['transitioned_expired']}")
    
    if dry_results['errors']:
        print(f"  Errors: {len(dry_results['errors'])}")
    
    if dry_results['transitioned_inconclusive'] + dry_results['transitioned_expired'] > 0:
        print("\nApplying transitions...")
        results = process_stale_reviews(dry_run=False)
        print(f"  [OK] Transitioned {results['transitioned_inconclusive']} to INCONCLUSIVE")
        print(f"  [OK] Transitioned {results['transitioned_expired']} to EXPIRED")
    else:
        print("\n[OK] No stale states found.")


if __name__ == "__main__":
    run_timeout_check()
