"""
Kaori Protocol — Multi-Agent Simulation Demo

Tests both TRUTH and FLOW layers with:
1. Multiple Agents with different standings
2. Network Edges (VOUCH, MEMBER_OF, COLLABORATE)
3. Multiple Observations from different reporters
4. Implicit Consensus checking
5. Signal-driven Mission creation
6. Full JSON output with observation references

This simulates a real deployment scenario.
"""
import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import (
    KaoriEngine,
    Observation,
    ReporterContext,
    Standing,
    Vote,
    VoteType,
    TruthStatus,
    Agent,
    AgentType,
    NetworkEdge,
    EdgeType,
    Signal,
    SignalType,
)
from core.schema_loader import get_claim_config
from core.models import Probe, ProbeStatus
from core.consensus import standing_to_weight
from core.signing import sign_truth_state
from core.validators.generalist import compute_confidence
from flow.engine.signal_processor import processor


# =============================================================================
# Configuration
# =============================================================================

IMAGE_PATH = Path(r"C:\Users\user\.gemini\antigravity\brain\3bb32cd3-0030-49ce-b6d9-3224f82b57ee\uploaded_image_1767494562623.jpg")
CLAIM_TYPE = "earth.flood.v1"
GEO_MALE = {"lat": 4.1755, "lon": 73.5093}


def print_header(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def main():
    print_header("KAORI PROTOCOL — MULTI-AGENT SIMULATION")
    
    # =========================================================================
    # Step 1: Create Agent Network (FLOW Layer)
    # =========================================================================
    print_header("STEP 1: CREATE AGENT NETWORK")
    
    # Initialize Engine to ensure DB tables exist
    engine = KaoriEngine(auto_sign=False)
    
    # Create agents with continuous standing
    agents = {
        "alice": Agent(
            agent_id=uuid4(),
            agent_type=AgentType.INDIVIDUAL,
            standing=Standing.BRONZE,
            trust_score=0.5,
            qualifications={"earth.flood": "field_reporter"},
        ),
        "bob": Agent(
            agent_id=uuid4(),
            agent_type=AgentType.INDIVIDUAL,
            standing=Standing.EXPERT,
            trust_score=0.85,
            qualifications={"earth.flood": "expert"},
        ),
        "carol": Agent(
            agent_id=uuid4(),
            agent_type=AgentType.INDIVIDUAL,
            standing=Standing.EXPERT,
            trust_score=0.82,
            qualifications={"earth.flood": "expert"},
        ),
        "dan": Agent(
            agent_id=uuid4(),
            agent_type=AgentType.INDIVIDUAL,
            standing=Standing.SILVER,
            trust_score=0.65,
        ),
        "msro_squad": Agent(
            agent_id=uuid4(),
            agent_type=AgentType.SQUAD,
            standing=Standing.AUTHORITY,
            trust_score=0.95,
            qualifications={"earth.flood": "official"},
        ),
    }
    
    print("  Agents Created:")
    for name, agent in agents.items():
        print(f"    {name}: {agent.agent_type.value}, standing={agent.standing.value}, trust={agent.trust_score:.2f}")
    
    # Create network edges
    edges = [
        NetworkEdge(
            edge_type=EdgeType.MEMBER_OF,
            source_agent_id=agents["bob"].agent_id,
            target_agent_id=agents["msro_squad"].agent_id,
            weight=1.0,
        ),
        NetworkEdge(
            edge_type=EdgeType.MEMBER_OF,
            source_agent_id=agents["carol"].agent_id,
            target_agent_id=agents["msro_squad"].agent_id,
            weight=1.0,
        ),
        NetworkEdge(
            edge_type=EdgeType.VOUCH,
            source_agent_id=agents["bob"].agent_id,
            target_agent_id=agents["alice"].agent_id,
            weight=0.8,
        ),
        NetworkEdge(
            edge_type=EdgeType.COLLABORATE,
            source_agent_id=agents["bob"].agent_id,
            target_agent_id=agents["carol"].agent_id,
            weight=1.0,
        ),
    ]
    
    print("\n  Network Edges:")
    for edge in edges:
        src = next(n for n, a in agents.items() if a.agent_id == edge.source_agent_id)
        tgt = next(n for n, a in agents.items() if a.agent_id == edge.target_agent_id)
        print(f"    {src} --[{edge.edge_type.value}]--> {tgt}")

    # =========================================================================
    # Step 2: Signal-Driven Mission Creation (FLOW Layer)
    # =========================================================================
    print_header("STEP 2: CREATE PROBE VIA SIGNAL")
    
    signal = Signal(
        type=SignalType.AUTOMATED_TRIGGER,
        source_id="rain_gauge_male_001",
        data={
            "claim_type": CLAIM_TYPE,
            "scope": {"type": "h3", "value": "886142a8e7fffff"},
            "trigger_reason": "water_level_exceeded_threshold",
            "bounty": 150,
        }
    )
    
    try:
        probe = processor.process_signal(signal)
        print(f"  Probe Created: {probe.probe_id}")
        print(f"  Status: {probe.status.value}")
    except Exception as e:
        print(f"  ⚠️  Probe creation skipped: {e}")

    # =========================================================================
    # Step 3: Multiple Observations (TRUTH Layer)
    # =========================================================================
    print_header("STEP 3: SUBMIT MULTIPLE OBSERVATIONS")
    
    # engine already initialized
    claim_config = get_claim_config(CLAIM_TYPE)
    
    # Load real image for AI confidence
    with open(IMAGE_PATH, "rb") as f:
        file_bytes = f.read()
    ai_confidence = compute_confidence(file_bytes, claim_type=CLAIM_TYPE)
    print(f"  AI Confidence (from real image): {ai_confidence:.2%}")
    
    # Create observations from different agents
    observations = []
    
    obs_data = [
        ("alice", 50.0, {"water_level_cm": 35, "affected_structures": True}),
        ("dan", 65.0, {"water_level_cm": 40, "flow_velocity": "moderate"}),
        ("bob", 200.0, {"water_level_cm": 38, "affected_structures": True, "official_report": True}),
    ]
    
    first_truthkey = None
    for reporter_name, standing_score, payload in obs_data:
        agent = agents[reporter_name]
        
        obs = Observation(
            claim_type=CLAIM_TYPE,
            reporter_id=str(agent.agent_id),
            reported_at=datetime.now(timezone.utc),
            reporter_context=ReporterContext(
                standing=agent.standing,
                trust_score=agent.trust_score,
                source_type="human"
            ),
            geo=GEO_MALE,
            payload=payload,
            evidence_refs=[f"gs://kaori-evidence/{reporter_name}_flood_{datetime.now().strftime('%H%M%S')}.jpg"],
            probe_id=probe.probe_id,
        )
        
        truth_state = engine.process_observation(obs)
        observations.append({
            "observation_id": str(obs.observation_id),
            "reporter": reporter_name,
            "standing": standing_score,
            "evidence_refs": obs.evidence_refs,
            "payload": payload,
        })
        
        if not first_truthkey:
            first_truthkey = truth_state.truthkey
            
        print(f"  ✅ {reporter_name} submitted observation ({agent.standing.value})")
    
    # Compute aggregate with real AI scores
    aggregate = {
        "observation_count": len(observations),
        "network_trust": sum(o["standing"] for o in observations),
        "ai_confidence_mean": ai_confidence,  # Use actual AI confidence
        "ai_variance": 0.0,  # No variance with single image
    }
    
    print(f"\n  Aggregate Metrics:")
    print(f"    Count: {aggregate['observation_count']}")
    print(f"    Network Trust: {aggregate['network_trust']:.1f}")
    print(f"    AI Mean: {aggregate['ai_confidence_mean']:.2%}")
    
    # Check intermediate status
    intermediate_status = engine.compute_intermediate_status(aggregate, claim_config)
    implicit_consensus = engine.check_implicit_consensus(aggregate, claim_config)
    
    print(f"\n  Intermediate Status: {intermediate_status.value}")
    print(f"  Implicit Consensus Met: {implicit_consensus}")

    # =========================================================================
    # Step 4: Voting (TRUTH Layer with Continuous Standing)
    # =========================================================================
    print_header("STEP 4: CONSENSUS VOTING")
    
    voters = [
        ("bob", 200.0, VoteType.RATIFY),
        ("carol", 180.0, VoteType.RATIFY),
        ("dan", 65.0, VoteType.RATIFY),
    ]
    
    for voter_name, standing, vote_type in voters:
        weight = standing_to_weight(standing)
        vote = Vote(
            voter_id=str(agents[voter_name].agent_id),
            voter_standing=standing,
            vote_type=vote_type,
            voted_at=datetime.now(timezone.utc),
        )
        truth_state = engine.apply_vote(first_truthkey, vote)
        print(f"  {voter_name} (standing={standing}, weight={weight:.2f}): {vote_type.value}")
    
    print(f"\n  Consensus Score: {truth_state.consensus.score}")
    print(f"  Finalized: {truth_state.consensus.finalized}")
    print(f"  Status: {truth_state.status.value}")

    # =========================================================================
    # Step 5: Sign and Output
    # =========================================================================
    print_header("STEP 5: SIGN & OUTPUT")
    
    truth_state.security = sign_truth_state(truth_state)
    print(f"  ✅ Truth State SIGNED")
    
    # Build comprehensive output with observation references
    output = {
        "truthkey": truth_state.truthkey.to_string(),
        "claim_type": truth_state.claim_type,
        "status": truth_state.status.value,
        "verification_basis": truth_state.verification_basis.value if truth_state.verification_basis else None,
        
        # Observations with references
        "observations": observations,
        "observation_count": len(observations),
        
        # Aggregate metrics
        "aggregate": {
            "network_trust": aggregate["network_trust"],
            "ai_confidence_mean": round(aggregate["ai_confidence_mean"], 4),
            "ai_variance": round(aggregate["ai_variance"], 6),
        },
        
        # Consensus
        "consensus": {
            "score": truth_state.consensus.score,
            "finalized": truth_state.consensus.finalized,
            "finalize_reason": truth_state.consensus.finalize_reason,
            "votes": [
                {
                    "voter_id": v.voter_id[:8] + "...",
                    "standing": v.voter_standing,
                    "vote": v.vote_type.value,
                }
                for v in truth_state.consensus.votes[-3:]  # Last 3 votes
            ]
        },
        
        # Security
        "security": {
            "truth_hash": truth_state.security.truth_hash,
            "truth_signature": truth_state.security.truth_signature,
            "signing_method": truth_state.security.signing_method,
            "signed_at": truth_state.security.signed_at.isoformat(),
        },
        
        # Flow metadata
        "intermediate_status": intermediate_status.value,
        "implicit_consensus_met": implicit_consensus,
    }
    
    print("\n" + json.dumps(output, indent=2, default=str))
    
    print_header("SIMULATION COMPLETE ✅")


if __name__ == "__main__":
    main()
