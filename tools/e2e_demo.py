"""
Kaori Protocol — End-to-End Demo (Real Image)

Demonstrates the full Kaori Protocol flow with:
1. Bouncer Validation
2. Generalist AI (CLIP)
3. TruthState with INTERMEDIATE statuses (LEANING_TRUE/FALSE)
4. Observation Aggregation
5. Human Voting (Continuous Standing)
6. Cryptographic Signing
7. Full JSON Output

NO MOCKS - Real AI, Real Database, Real Signing
"""
import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import (
    KaoriEngine,
    Observation,
    ReporterContext,
    Standing,
    Vote,
    VoteType,
    TruthStatus,
)
from core.validators import bouncer
from core.validators.generalist import compute_confidence, check_content_safety
from core.schema_loader import get_claim_config
from core.consensus import standing_to_weight


# =============================================================================
# Configuration
# =============================================================================

IMAGE_PATH = Path(r"C:\Users\user\.gemini\antigravity\brain\3bb32cd3-0030-49ce-b6d9-3224f82b57ee\uploaded_image_1767494562623.jpg")
CLAIM_TYPE = "earth.flood.v1"
REPORTER_ID = "field_reporter_alice"
GEO = {"lat": 4.1755, "lon": 73.5093}


def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def main():
    print_header("KAORI PROTOCOL — END-TO-END DEMO v2")
    print(f"Image: {IMAGE_PATH}")
    print(f"Claim Type: {CLAIM_TYPE}")
    
    if not IMAGE_PATH.exists():
        print(f"❌ ERROR: Image not found")
        return
    
    with open(IMAGE_PATH, "rb") as f:
        file_bytes = f.read()
    print(f"✅ Image loaded: {len(file_bytes):,} bytes")
    
    # =========================================================================
    # Step 1: Bouncer Validation
    # =========================================================================
    print_header("STEP 1: BOUNCER VALIDATION")
    ok, reason = bouncer.validate_image_file(file_bytes)
    print(f"  Image Valid: {'✅ PASS' if ok else f'❌ FAIL: {reason}'}")
    phash = bouncer.compute_phash(file_bytes)
    print(f"  pHash: {phash}")
    
    if not ok:
        print("\n❌ BOUNCER REJECTED")
        return
    
    # =========================================================================
    # Step 2: Generalist AI (CLIP)
    # =========================================================================
    print_header("STEP 2: GENERALIST AI VALIDATION")
    ai_confidence = compute_confidence(file_bytes, claim_type=CLAIM_TYPE)
    print(f"  AI Confidence: {ai_confidence:.2%}")
    
    # =========================================================================
    # Step 3: Create TruthState with Intermediate Status
    # =========================================================================
    print_header("STEP 3: CREATE TRUTH STATE (INTERMEDIATE)")
    
    engine = KaoriEngine(auto_sign=False)  # Don't sign until final
    claim_config = get_claim_config(CLAIM_TYPE)
    
    observation = Observation(
        claim_type=CLAIM_TYPE,
        reporter_id=REPORTER_ID,
        reported_at=datetime.now(timezone.utc),
        reporter_context=ReporterContext(
            standing=Standing.BRONZE,
            trust_score=0.5,
            source_type="human"
        ),
        geo=GEO,
        payload={"water_level_cm": 35, "affected_structures": True},
        evidence_refs=["gs://kaori-evidence/flood_demo.jpg"],
    )
    
    # Compute aggregate for intermediate status
    aggregate = engine.compute_observation_aggregate(
        observations=[observation],
        ai_scores=[ai_confidence]
    )
    print(f"  Observation Aggregate:")
    print(f"    Count: {aggregate['observation_count']}")
    print(f"    Network Trust: {aggregate['network_trust']:.1f}")
    print(f"    AI Mean: {aggregate['ai_confidence_mean']:.2%}")
    print(f"    AI Variance: {aggregate['ai_variance']:.4f}")
    
    # Compute intermediate status (LEANING_TRUE/FALSE/UNDECIDED)
    intermediate_status = engine.compute_intermediate_status(aggregate, claim_config)
    print(f"\n  Intermediate Status: {intermediate_status.value}")
    
    # Check implicit consensus
    can_auto_verify = engine.check_implicit_consensus(aggregate, claim_config)
    print(f"  Implicit Consensus Met: {can_auto_verify}")
    
    # Process observation (persists with intermediate status)
    truth_state = engine.process_observation(observation)
    print(f"\n  TruthKey: {truth_state.truthkey.to_string()}")
    print(f"  Current Status: {truth_state.status.value}")
    
    # =========================================================================
    # Step 4: Human Voting (Continuous Standing)
    # =========================================================================
    print_header("STEP 4: HUMAN VOTING (CONTINUOUS STANDING)")
    
    voters = [
        ("expert_bob", 200.0, VoteType.RATIFY),
        ("expert_carol", 180.0, VoteType.RATIFY),
        ("silver_dan", 50.0, VoteType.RATIFY),
    ]
    
    for voter_id, standing, vote_type in voters:
        weight = standing_to_weight(standing)
        vote = Vote(
            voter_id=voter_id,
            voter_standing=standing,
            vote_type=vote_type,
            voted_at=datetime.now(timezone.utc),
        )
        truth_state = engine.apply_vote(truth_state.truthkey, vote)
        score = truth_state.consensus.score if truth_state.consensus else 0
        print(f"  {voter_id} (standing={standing}, weight={weight:.2f}): {vote_type.value} → Score: {score}")
    
    print(f"\n  Final Status: {truth_state.status.value}")
    print(f"  Consensus Score: {truth_state.consensus.score}")
    print(f"  Finalized: {truth_state.consensus.finalized}")
    
    # =========================================================================
    # Step 5: Cryptographic Signing
    # =========================================================================
    print_header("STEP 5: CRYPTOGRAPHIC SIGNING")
    
    from core.signing import sign_truth_state
    truth_state.security = sign_truth_state(truth_state)
    print(f"  ✅ Truth state SIGNED")
    print(f"  Hash: {truth_state.security.truth_hash[:40]}...")
    print(f"  Signature: {truth_state.security.truth_signature[:40]}...")
    
    # =========================================================================
    # Step 6: Full JSON Output
    # =========================================================================
    print_header("STEP 6: FULL JSON OUTPUT")
    
    # Convert to flattened JSON
    output = {
        "truthkey": truth_state.truthkey.to_string(),
        "claim_type": truth_state.claim_type,
        "status": truth_state.status.value,
        "verification_basis": truth_state.verification_basis.value if truth_state.verification_basis else None,
        "ai_confidence": round(ai_confidence, 4),
        "confidence": round(truth_state.confidence, 4),
        "observation_count": len(truth_state.observation_ids),
        "evidence_refs": truth_state.evidence_refs[:3],
        "transparency_flags": truth_state.transparency_flags,
        "consensus": {
            "score": truth_state.consensus.score,
            "finalized": truth_state.consensus.finalized,
            "finalize_reason": truth_state.consensus.finalize_reason,
            "vote_count": len(truth_state.consensus.votes),
        },
        "security": {
            "truth_hash": truth_state.security.truth_hash,
            "truth_signature": truth_state.security.truth_signature,
            "signing_method": truth_state.security.signing_method,
            "key_id": truth_state.security.key_id,
            "signed_at": truth_state.security.signed_at.isoformat() if truth_state.security.signed_at else None,
        },
        "aggregate": aggregate,
        "intermediate_status": intermediate_status.value,
        "implicit_consensus_met": can_auto_verify,
    }
    
    print(json.dumps(output, indent=2, default=str))
    
    print_header("DEMO COMPLETE ✅")


if __name__ == "__main__":
    main()
