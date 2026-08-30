"""API runtime must not apply DDL and must require production signing on Cloud SQL."""
from __future__ import annotations

import pytest
from kaori_api.app import create_stores
from kaori_truth.signing import SigningConfigError

CLOUD_SQL = "postgresql://kaori_runtime@/cloudsql/msro-kaori-sandbox:asia-southeast1:kaori/kaori"


class _FakeEngine:
    class dialect:
        name = "postgresql"


class _FakeStore:
    def __init__(self, *args, **kwargs):
        self.engine = _FakeEngine()

    def ensure_schema(self):
        raise AssertionError("API runtime must not call ensure_schema()")


def test_create_stores_requires_production_signing_for_cloud_sql(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", CLOUD_SQL)
    monkeypatch.delenv("KAORI_SIGNING_KEY", raising=False)
    monkeypatch.delenv("KAORI_SIGNING_KEY_ID", raising=False)
    with pytest.raises(SigningConfigError, match="dedicated production secret"):
        create_stores()


def test_create_stores_checks_schema_and_never_runs_ddl(monkeypatch):
    required = []

    monkeypatch.setenv("DATABASE_URL", CLOUD_SQL)
    monkeypatch.setenv("KAORI_SIGNING_KEY", "production-truthstate-hmac")
    monkeypatch.setenv("KAORI_SIGNING_KEY_ID", "msro-kaori-prod-1")
    monkeypatch.setenv("KAORI_VALIDATOR_SIGNING_KEY", "generalist-validator-hmac")
    monkeypatch.setattr("kaori_db.PostgresSignalStore", _FakeStore)
    monkeypatch.setattr("kaori_db.PostgresObservationStore", _FakeStore)
    monkeypatch.setattr("kaori_db.PostgresTruthArtifactStore", _FakeStore)
    monkeypatch.setattr(
        "kaori_db.store.require_kaori_schema",
        lambda engine: required.append(engine),
    )

    signals, observations, artifacts = create_stores()
    assert required
    assert isinstance(signals, _FakeStore)
    assert isinstance(observations, _FakeStore)
    assert isinstance(artifacts, _FakeStore)
