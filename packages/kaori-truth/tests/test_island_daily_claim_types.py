"""Nakaiy is the island-daily ClaimType the published timetable still opens.

These tests load published YAML and call the existing compiler.
They do not change compile_truth_state. A human window is not a TruthKey.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from kaori_truth import compile_truth_state
from kaori_truth.factory import load_claim_type
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthkey import build_truthkey, parse_truthkey
from kaori_truth.trust_snapshot import AgentTrust, TrustSnapshot

SCHEMAS = Path(__file__).resolve().parents[2] / "kaori-spec" / "schemas" / "earth"
COMPILE_TIME = datetime(2026, 1, 7, 14, 35, 0, tzinfo=timezone.utc)
LOCATION = {"lat": 4.175, "lon": 73.509}

DAILY = {
    "earth.nakaiy.v1": ("nakaiy", 6),
}


def _load(name: str):
    return load_claim_type(SCHEMAS / name)


def _observation(claim_type: str, payload: dict, reporter_id: str = "user:observer-1") -> Observation:
    return Observation(
        observation_id=UUID("11111111-1111-1111-1111-111111111111"),
        claim_type=claim_type,
        reported_at=COMPILE_TIME,
        reporter_id=reporter_id,
        reporter_context=ReporterContext(
            standing=Standing.SILVER,
            trust_score=0.75,
            source_type="human",
        ),
        geo={"lat": LOCATION["lat"], "lon": LOCATION["lon"]},
        payload=payload,
        evidence_refs=[EvidenceRef(uri="gs://kaori-evidence/gauge.jpg", sha256="a" * 64)],
    )


def _trust(reporter_id: str = "user:observer-1") -> TrustSnapshot:
    return TrustSnapshot.create(
        snapshot_id="snapshot-daily",
        snapshot_time=COMPILE_TIME,
        agent_trusts={
            reporter_id: AgentTrust(
                agent_id=reporter_id,
                effective_trust=150.0,
                standing=150.0,
                derived_class="silver",
                flags=[],
            )
        },
    )


def _compile(claim_type, truth_key: str, payload: dict):
    return compile_truth_state(
        claim_type=claim_type,
        truth_key=truth_key,
        observations=[_observation(claim_type.id, payload)],
        trust_snapshot=_trust(),
        policy_version=claim_type.policy_version,
        compile_time=COMPILE_TIME,
    )


def test_daily_types_set_an_explicit_floor_of_three_and_a_day_bucket():
    for claim_id, (topic, resolution) in DAILY.items():
        claim_type = _load(f"{topic}_v1.yaml")
        assert claim_type.id == claim_id
        assert claim_type.truthkey.time_bucket == "P1D"
        assert claim_type.truthkey.resolution == resolution
        assert claim_type.truthkey.spatial_system == "h3"
        assert claim_type.truthkey.z_index == "surface"
        assert claim_type.minimum_observations() == 3
        claim_type.validate_domain_config()
        fields = [
            field["name"]
            for field in claim_type.get_config()["ui_schema"]["fields"]
            if field.get("required")
        ]
        assert fields == ["period_name", "rain", "wind", "sea", "sky"]
        assert list(claim_type.output_schema["properties"]) == fields
        implicit = claim_type.get_config()["implicit_consensus"]
        assert implicit["enabled"] is True
        assert implicit["min_observations"] == 3


def test_truthkey_is_an_iso_bucket_not_a_human_window():
    event = datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc)
    for claim_id, (topic, resolution) in DAILY.items():
        key = build_truthkey(
            claim_type_id=claim_id,
            event_time=event,
            spatial_system="h3",
            spatial_resolution=resolution,
            z_index="surface",
            location=LOCATION,
            time_bucket_duration="P1D",
        )
        parts = parse_truthkey(key)
        assert parts.domain == "earth"
        assert parts.topic == topic
        assert parts.spatial_system == "h3"
        assert parts.z_index == "surface"
        assert parts.time_bucket == "2026-01-02T00:00Z"
        assert "48 hours" not in key
        assert "hour" not in parts.time_bucket


def test_nakaiy_output_is_the_comparison_not_a_failed_tradition():
    claim_type = _load("nakaiy_v1.yaml")
    state = _compile(
        claim_type,
        "earth:nakaiy:h3:abc:surface:2026-01-07T00:00Z",
        {"period_name": "Mula", "rain": "light", "wind": "east", "sea": "rough", "sky": "clear"},
    )
    assert state.claim == {
        "period_name": "Mula",
        "rain": "light",
        "wind": "east",
        "sea": "rough",
        "sky": "clear",
    }
    assert "tradition_failed" not in state.claim
    assert "nakaiy_wrong" not in state.claim
