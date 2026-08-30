"""Production TruthState signing must not silently use the development key."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaori_truth.primitives.claimtype import ClaimType
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.signing import (
    DEV_SIGNING_KEY,
    DEV_SIGNING_KEY_ID,
    SigningConfigError,
    sign_truth_state,
    signing_config,
    verify_signature,
)
from kaori_truth import compile_truth_state
from kaori_truth.trust_snapshot import AgentTrust, TrustSnapshot
from uuid import UUID

COMPILE_TIME = datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc)
CLOUD_SQL = "postgresql://kaori_runtime@/cloudsql/msro-kaori-sandbox:asia-southeast1:kaori/kaori"


def _unsigned_state():
    claim_type = ClaimType(
        id="earth.flood.v1",
        version=1,
        domain="earth",
        topic="flood",
        output_schema={
            "type": "object",
            "properties": {
                "severity": {"type": "string"},
                "water_level_meters": {"type": "number"},
                "observation_count": {"type": "integer"},
                "network_trust": {"type": "number"},
            },
        },
    )
    observation = Observation(
        observation_id=UUID("11111111-1111-1111-1111-111111111111"),
        claim_type="earth.flood.v1",
        reported_at=COMPILE_TIME,
        reporter_id="agent-001",
        reporter_context=ReporterContext(
            standing=Standing.SILVER,
            trust_score=0.75,
            source_type="human",
        ),
        geo={"lat": 4.175, "lon": 73.509},
        payload={"water_level": "1.5", "severity": "moderate"},
        evidence_refs=[EvidenceRef(uri="gs://kaori-observations/a.jpg", sha256="a" * 64)],
    )
    snapshot = TrustSnapshot.create(
        snapshot_id="snapshot-001",
        snapshot_time=COMPILE_TIME,
        agent_trusts={
            "agent-001": AgentTrust(
                agent_id="agent-001",
                effective_trust=150.0,
                standing=150.0,
                derived_class="silver",
            )
        },
    )
    return compile_truth_state(
        claim_type=claim_type,
        truth_key="earth:flood:h3:886142a8e7fffff:surface:2026-01-07T12:00Z",
        observations=[observation],
        trust_snapshot=snapshot,
        policy_version="earth.flood.v1.policy.1",
        compiler_version="2.0.0",
        compile_time=COMPILE_TIME,
    )


def test_local_runs_may_use_development_key(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("KAORI_ENVIRONMENT", raising=False)
    monkeypatch.delenv("KAORI_SIGNING_KEY", raising=False)
    monkeypatch.delenv("KAORI_SIGNING_KEY_ID", raising=False)
    key, key_id = signing_config()
    assert key == DEV_SIGNING_KEY.encode("utf-8")
    assert key_id == DEV_SIGNING_KEY_ID


def test_cloud_sql_rejects_missing_or_dev_signing_key(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", CLOUD_SQL)
    monkeypatch.delenv("KAORI_SIGNING_KEY", raising=False)
    monkeypatch.delenv("KAORI_SIGNING_KEY_ID", raising=False)
    with pytest.raises(SigningConfigError, match="dedicated production secret"):
        signing_config()

    monkeypatch.setenv("KAORI_SIGNING_KEY", DEV_SIGNING_KEY)
    monkeypatch.setenv("KAORI_SIGNING_KEY_ID", "msro-kaori-prod-1")
    with pytest.raises(SigningConfigError, match="dedicated production secret"):
        signing_config()


def test_cloud_sql_rejects_dev_key_id_and_validator_key_reuse(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", CLOUD_SQL)
    monkeypatch.setenv("KAORI_SIGNING_KEY", "production-truthstate-hmac")
    monkeypatch.setenv("KAORI_SIGNING_KEY_ID", DEV_SIGNING_KEY_ID)
    with pytest.raises(SigningConfigError, match="dedicated production key id"):
        signing_config()

    monkeypatch.setenv("KAORI_SIGNING_KEY_ID", "msro-kaori-prod-1")
    monkeypatch.setenv("KAORI_VALIDATOR_SIGNING_KEY", "production-truthstate-hmac")
    with pytest.raises(SigningConfigError, match="distinct from KAORI_VALIDATOR_SIGNING_KEY"):
        signing_config()


def test_production_signing_uses_configured_key_and_id(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", CLOUD_SQL)
    monkeypatch.setenv("KAORI_SIGNING_KEY", "production-truthstate-hmac")
    monkeypatch.setenv("KAORI_SIGNING_KEY_ID", "msro-kaori-prod-1")
    monkeypatch.setenv("KAORI_VALIDATOR_SIGNING_KEY", "generalist-validator-hmac")
    signed = sign_truth_state(_unsigned_state(), COMPILE_TIME)
    assert signed.security.key_id == "msro-kaori-prod-1"
    assert verify_signature(signed)

    monkeypatch.setenv("KAORI_SIGNING_KEY", "a-different-production-hmac")
    assert not verify_signature(signed)


def test_sqlite_database_url_is_not_treated_as_cloud_sql(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("KAORI_ENVIRONMENT", raising=False)
    monkeypatch.delenv("KAORI_SIGNING_KEY", raising=False)
    key, key_id = signing_config()
    assert key == DEV_SIGNING_KEY.encode("utf-8")
    assert key_id == DEV_SIGNING_KEY_ID
