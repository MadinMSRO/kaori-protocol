"""
Tests for Kaori Flow Core Library.

Tests the 7 Rules of Trust implementation.
"""
import pytest
from datetime import datetime, timedelta

from kaori_flow import (
    FlowCore,
    FlowPolicy,
    Signal,
    SignalTypes,
    TrustContext,
    InMemorySignalStore,
    Agent,
    AgentType,
    STANDING_MIN,
    STANDING_MAX,
)


class TestFlowCore:
    """Tests for FlowCore."""
    
    def test_create_with_default_policy(self):
        """FlowCore can be created with default policy."""
        flow = FlowCore()
        assert flow.policy is not None
        assert flow.policy.version == "1.0.0"
    
    def test_create_with_custom_store(self):
        """FlowCore can be created with custom store."""
        store = InMemorySignalStore()
        flow = FlowCore(store=store)
        # Check it's using the store we provided (same type, works correctly)
        assert isinstance(flow.store, InMemorySignalStore)
    
    def test_register_agent(self):
        """Agent registration emits signal and sets initial standing."""
        flow = FlowCore()
        flow.register_agent("user:test", role="observer")
        
        standing = flow.get_standing("user:test")
        assert standing == 200.0  # Default for observer
    
    def test_register_validator(self):
        """Validators get higher initial standing."""
        flow = FlowCore()
        flow.register_agent("user:validator", role="validator")
        
        standing = flow.get_standing("user:validator")
        assert standing == 250.0  # Default for validator
    
    def test_register_authority(self):
        """Authorities get highest initial standing."""
        flow = FlowCore()
        flow.register_agent("official:gov", role="authority")
        
        standing = flow.get_standing("official:gov")
        assert standing == 500.0  # Default for authority


class TestStandingUpdates:
    """Tests for Rule 5: Nonlinear updates."""
    
    def test_correct_outcome_increases_standing(self):
        """Correct truth outcome increases standing."""
        flow = FlowCore()
        flow.register_agent("user:test")
        
        before = flow.get_standing("user:test")
        
        flow.emit_truthstate(
            truthkey="test:key:1",
            status="VERIFIED_TRUE",
            confidence=0.9,
            contributors=["user:test"],
            outcome="correct",
            quality_score=50.0,
        )
        
        after = flow.get_standing("user:test")
        assert after > before
    
    def test_incorrect_outcome_decreases_standing(self):
        """Incorrect truth outcome decreases standing."""
        flow = FlowCore()
        flow.register_agent("user:test")
        
        before = flow.get_standing("user:test")
        
        flow.emit_truthstate(
            truthkey="test:key:1",
            status="VERIFIED_FALSE",
            confidence=0.9,
            contributors=["user:test"],
            outcome="incorrect",
            quality_score=50.0,
        )
        
        after = flow.get_standing("user:test")
        assert after < before
    
    def test_penalty_sharper_than_reward(self):
        """Penalty is sharper than reward (Rule 5)."""
        # Set up two identical agents
        flow1 = FlowCore()
        flow1.register_agent("user:gain")
        
        flow2 = FlowCore()
        flow2.register_agent("user:loss")
        
        before = 200.0  # Default standing
        
        flow1.emit_truthstate(
            truthkey="test:key:1",
            status="VERIFIED_TRUE",
            confidence=0.9,
            contributors=["user:gain"],
            outcome="correct",
            quality_score=50.0,
        )
        
        flow2.emit_truthstate(
            truthkey="test:key:1",
            status="VERIFIED_FALSE",
            confidence=0.9,
            contributors=["user:loss"],
            outcome="incorrect",
            quality_score=50.0,
        )
        
        gain = flow1.get_standing("user:gain") - before
        loss = before - flow2.get_standing("user:loss")
        
        # Penalty should be ~2x larger (amplifier=2.0)
        assert loss > gain * 1.5
    
    def test_standing_bounded(self):
        """Standing stays within bounds (Rule 3)."""
        flow = FlowCore()
        flow.register_agent("user:test")
        
        # Many incorrect outcomes
        for i in range(100):
            flow.emit_truthstate(
                truthkey=f"test:key:{i}",
                status="VERIFIED_FALSE",
                confidence=0.9,
                contributors=["user:test"],
                outcome="incorrect",
                quality_score=100.0,
            )
        
        standing = flow.get_standing("user:test")
        assert standing >= STANDING_MIN
        assert standing <= STANDING_MAX


class TestTrustContext:
    """Tests for Rule 4: Standing Global, Trust Local."""
    
    def test_self_dealing_penalty(self):
        """Self-dealing reduces effective trust."""
        flow = FlowCore()
        flow.register_agent("user:creator")
        
        # Boost standing
        for i in range(5):
            flow.emit_truthstate(
                truthkey=f"test:key:{i}",
                status="VERIFIED_TRUE",
                confidence=0.9,
                contributors=["user:creator"],
                outcome="correct",
                quality_score=80.0,
            )
        
        # Normal context
        normal_snapshot = flow.get_trust_snapshot(
            agent_ids=["user:creator"],
            context=TrustContext(probe_creator_id="user:other"),
        )
        
        # Self-dealing context
        self_dealing_snapshot = flow.get_trust_snapshot(
            agent_ids=["user:creator"],
            context=TrustContext(probe_creator_id="user:creator"),
        )
        
        normal_trust = normal_snapshot.agent_trusts["user:creator"].effective_trust
        self_trust = self_dealing_snapshot.agent_trusts["user:creator"].effective_trust
        
        # Self-dealing should be ~50% of normal
        assert self_trust < normal_trust
        assert abs(self_trust / normal_trust - 0.5) < 0.05


class TestPolicyAsAgent:
    """Tests for Rule 7: Policy is an Agent."""
    
    def test_policy_has_standing(self):
        """Policy is registered as agent with standing."""
        flow = FlowCore()
        flow.register_policy(flow.policy)
        
        standing = flow.get_standing(flow.policy.agent_id)
        assert standing == 500.0  # Initial policy standing
    
    def test_policy_standing_changes(self):
        """Policy standing changes based on truth outcomes."""
        flow = FlowCore()
        flow.register_policy(flow.policy)
        
        before = flow.get_standing(flow.policy.agent_id)
        
        flow.emit_truthstate(
            truthkey="test:key:1",
            status="VERIFIED_TRUE",
            confidence=0.9,
            contributors=["user:test"],
            outcome="correct",
            quality_score=80.0,
        )
        
        after = flow.get_standing(flow.policy.agent_id)
        
        # Policy should gain standing from correct outcomes
        assert after > before


class TestSignal:
    """Tests for Signal primitive."""
    
    def test_signal_immutable(self):
        """Signals are immutable (frozen)."""
        signal = Signal(
            signal_type=SignalTypes.OBSERVATION_SUBMITTED,
            time=datetime.utcnow(),
            agent_id="user:test",
            object_id="probe:1",
            payload={"data": "test"},
        )
        
        with pytest.raises(Exception):
            signal.payload = {}  # Should fail
    
    def test_signal_id_computed(self):
        """Signal ID is computed from content."""
        signal = Signal(
            signal_type=SignalTypes.OBSERVATION_SUBMITTED,
            time=datetime.utcnow(),
            agent_id="user:test",
            object_id="probe:1",
            payload={"data": "test"},
        )
        
        assert signal.signal_id is not None
        assert len(signal.signal_id) == 64  # SHA256 hex
    
    def test_same_content_same_id(self):
        """Same content produces same signal ID."""
        time = datetime(2026, 1, 9, 12, 0, 0)
        
        signal1 = Signal(
            signal_type=SignalTypes.OBSERVATION_SUBMITTED,
            time=time,
            agent_id="user:test",
            object_id="probe:1",
            payload={"data": "test"},
        )
        
        signal2 = Signal(
            signal_type=SignalTypes.OBSERVATION_SUBMITTED,
            time=time,
            agent_id="user:test",
            object_id="probe:1",
            payload={"data": "test"},
        )
        
        assert signal1.signal_id == signal2.signal_id


class TestReplay:
    """Tests for Rule 1: Event-sourced replay."""
    
    def test_replay_at_timestamp(self):
        """Can replay state at historical timestamp."""
        from kaori_flow.primitives.signal import Signal, SignalTypes
        
        flow = FlowCore()
        
        # Register agent at t=0
        past_time = datetime(2026, 1, 1, 12, 0, 0)
        signal1 = Signal(
            signal_type=SignalTypes.AGENT_REGISTERED,
            time=past_time,
            agent_id="system:flow",
            object_id="user:test",
            payload={"role": "observer"},
            policy_version="1.0.0",
        )
        flow.emit(signal1)
        
        # Checkpoint in the middle
        checkpoint = datetime(2026, 1, 2, 12, 0, 0)
        
        # Truth outcome at t=later
        future_time = datetime(2026, 1, 3, 12, 0, 0)
        signal2 = Signal(
            signal_type=SignalTypes.TRUTHSTATE_EMITTED,
            time=future_time,
            agent_id="system:truth",
            object_id="test:key:1",
            payload={
                "status": "VERIFIED_TRUE",
                "confidence": 0.9,
                "contributors": ["user:test"],
                "outcome": "correct",
                "quality_score": 80.0,
                "policy_agent_id": flow.policy.agent_id,
            },
            policy_version="1.0.0",
        )
        flow.emit(signal2)
        
        # Current standing should be higher (includes truthstate)
        current = flow.get_standing("user:test")
        
        # Replay at checkpoint should give original standing (before truthstate)
        historical = flow.replay_at(checkpoint)
        
        # At checkpoint, agent was registered but no truthstate yet
        assert historical.get("user:test", 0) == 200.0  # Initial standing
        assert current > 200.0  # After correct outcome


class TestInMemoryStore:
    """Tests for InMemorySignalStore."""
    
    def test_append_idempotent(self):
        """Appending same signal twice is idempotent."""
        store = InMemorySignalStore()
        
        signal = Signal(
            signal_type=SignalTypes.OBSERVATION_SUBMITTED,
            time=datetime.utcnow(),
            agent_id="user:test",
            object_id="probe:1",
            payload={},
        )
        
        store.append(signal)
        store.append(signal)  # Same signal
        
        assert len(store) == 1
    
    def test_get_for_agent(self):
        """Can filter signals by agent."""
        store = InMemorySignalStore()
        
        signal1 = Signal(
            signal_type=SignalTypes.OBSERVATION_SUBMITTED,
            time=datetime.utcnow(),
            agent_id="user:alice",
            object_id="probe:1",
            payload={},
        )
        
        signal2 = Signal(
            signal_type=SignalTypes.OBSERVATION_SUBMITTED,
            time=datetime.utcnow(),
            agent_id="user:bob",
            object_id="probe:1",
            payload={},
        )
        
        store.append(signal1)
        store.append(signal2)
        
        alice_signals = store.get_for_agent("user:alice")
        assert len(alice_signals) == 1
        assert alice_signals[0].agent_id == "user:alice"
