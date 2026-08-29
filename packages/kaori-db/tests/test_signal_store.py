"""PostgresSignalStore satisfies kaori_flow.store.SignalStore."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaori_db import PostgresSignalStore
from kaori_flow import FlowCore, SignalStore
from kaori_flow.primitives.signal import Signal, SignalTypes


@pytest.fixture
def store(tmp_path) -> PostgresSignalStore:
    url = f"sqlite:///{tmp_path / 'signals.db'}"
    impl = PostgresSignalStore(url)
    impl.ensure_schema()
    return impl


def _signal(
    *,
    signal_type: str = SignalTypes.OBSERVATION_SUBMITTED,
    time: datetime | None = None,
    agent_id: str = "user:alice",
    object_id: str = "probe:1",
    payload: dict | None = None,
) -> Signal:
    return Signal(
        signal_type=signal_type,
        time=time or datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc),
        agent_id=agent_id,
        object_id=object_id,
        payload=payload or {},
    )


def test_satisfies_protocol(store: PostgresSignalStore):
    assert isinstance(store, SignalStore)


def test_append_idempotent_on_signal_id(store: PostgresSignalStore):
    signal = _signal()
    store.append(signal)
    store.append(signal)
    assert len(store.get_all()) == 1
    assert store.get_all()[0].signal_id == signal.signal_id


def test_get_all_ordered_by_time(store: PostgresSignalStore):
    later = _signal(time=datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc), object_id="probe:2")
    earlier = _signal(time=datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc), object_id="probe:0")
    store.append(later)
    store.append(earlier)
    times = [s.time for s in store.get_all()]
    assert times == sorted(times)


def test_get_for_agent_emitter_or_object(store: PostgresSignalStore):
    as_emitter = _signal(agent_id="user:alice", object_id="probe:1")
    as_object = _signal(
        signal_type=SignalTypes.AGENT_REGISTERED,
        agent_id="system:flow",
        object_id="user:alice",
        time=datetime(2026, 1, 7, 13, 0, tzinfo=timezone.utc),
    )
    other = _signal(
        agent_id="user:bob",
        object_id="probe:9",
        time=datetime(2026, 1, 7, 14, 0, tzinfo=timezone.utc),
    )
    store.append(as_emitter)
    store.append(as_object)
    store.append(other)
    alice = store.get_for_agent("user:alice")
    assert {s.signal_id for s in alice} == {as_emitter.signal_id, as_object.signal_id}


def test_get_since(store: PostgresSignalStore):
    old = _signal(time=datetime(2026, 1, 1, tzinfo=timezone.utc), object_id="probe:old")
    new = _signal(time=datetime(2026, 1, 10, tzinfo=timezone.utc), object_id="probe:new")
    store.append(old)
    store.append(new)
    since = datetime(2026, 1, 5, tzinfo=timezone.utc)
    assert [s.object_id for s in store.get_since(since)] == ["probe:new"]


def test_get_by_type(store: PostgresSignalStore):
    obs = _signal(signal_type=SignalTypes.OBSERVATION_SUBMITTED)
    endorsement = _signal(
        signal_type=SignalTypes.ENDORSEMENT,
        time=datetime(2026, 1, 7, 15, 0, tzinfo=timezone.utc),
        object_id="user:bob",
    )
    store.append(obs)
    store.append(endorsement)
    assert [s.signal_id for s in store.get_by_type(SignalTypes.ENDORSEMENT)] == [endorsement.signal_id]


def test_flow_uses_store_when_injected(store: PostgresSignalStore):
    flow = FlowCore(store=store)
    flow.register_agent("user:alice", role="observer")
    assert flow.store is store
    assert flow.get_standing("user:alice") == 200.0
    assert store.get_by_type(SignalTypes.AGENT_REGISTERED)


def test_create_store_uses_database_url(monkeypatch, tmp_path):
    url = f"sqlite:///{tmp_path / 'from-env.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    from kaori_api.app import create_store

    store = create_store()
    assert isinstance(store, PostgresSignalStore)
    store.append(_signal())
    assert len(store.get_all()) == 1


def test_create_store_inmemory_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from kaori_api.app import create_store
    from kaori_flow import InMemorySignalStore

    store = create_store()
    assert isinstance(store, InMemorySignalStore)
