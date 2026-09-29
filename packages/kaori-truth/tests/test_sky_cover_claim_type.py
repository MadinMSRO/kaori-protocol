"""earth.sky_cover.v1: cloud cover and rain, doable anywhere outdoors.

The first field test's claim (IAC 2026, Antalya). It runs the same lane as
earth.flood_water.v1, so a test of it proves the flood path: three reporters
in one hexagon-hour, then the AI check and a human ratify.
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

ROOT = Path(__file__).resolve().parents[2] / "kaori-spec" / "schemas"
EVENT = datetime(2026, 10, 5, 9, 20, tzinfo=timezone.utc)
ANTALYA = {"lat": 36.8969, "lon": 30.7133}
KEY = "earth:sky_cover:h3:883f6e36d3fffff:surface:2026-10-05T09:00Z"


def _load():
    return load_claim_type(ROOT / "earth" / "sky_cover_v1.yaml")


def test_sky_cover_runs_the_flood_lane():
    sky = _load()
    water = load_claim_type(ROOT / "earth" / "flood_water_v1.yaml")
    assert sky.id == "earth.sky_cover.v1"
    assert (sky.domain, sky.topic) == ("earth", "sky_cover")
    assert sky.risk_profile == water.risk_profile == "critical"
    assert (sky.truthkey.spatial_system, sky.truthkey.resolution, sky.truthkey.time_bucket) == ("h3", 8, "PT1H")
    assert sky.minimum_observations() == water.minimum_observations() == 3
    sky.validate_domain_config()
    fields = [f["name"] for f in sky.get_config()["ui_schema"]["fields"]]
    assert list(sky.output_schema["properties"]) == fields
    assert sky.output_schema["required"] == ["cover", "raining"]
    assert sky.output_schema["properties"]["cover"]["enum"] == ["clear", "few", "scattered", "broken", "overcast"]


def test_sky_cover_truthkey_is_the_hexagon_and_the_hour():
    sky = _load()
    key = build_truthkey(
        claim_type_id=sky.id,
        event_time=EVENT,
        location=ANTALYA,
        spatial_system=sky.truthkey.spatial_system,
        spatial_resolution=sky.truthkey.resolution,
        z_index=sky.truthkey.z_index,
        time_bucket_duration=sky.truthkey.time_bucket,
    )
    assert key == KEY
    assert parse_truthkey(key).topic == "sky_cover"


def _observation(n: int, cover: str, raining: bool) -> Observation:
    return Observation(
        observation_id=UUID(f"{n:08d}-2222-2222-2222-222222222222"),
        claim_type="earth.sky_cover.v1",
        reported_at=EVENT,
        reporter_id=f"user:reporter-{n}",
        reporter_context=ReporterContext(standing=Standing.SILVER, trust_score=0.75, source_type="human"),
        geo=ANTALYA,
        payload={"cover": cover, "raining": raining},
        evidence_refs=[EvidenceRef(uri=f"gs://kaori-evidence/sky-{n}.jpg", sha256=f"{n}" * 64)],
    )


def _compile(observations):
    sky = _load()
    trust = TrustSnapshot.create(
        snapshot_id="snapshot-sky-cover",
        snapshot_time=EVENT,
        agent_trusts={
            o.reporter_id: AgentTrust(agent_id=o.reporter_id, effective_trust=150.0, standing=150.0, derived_class="silver", flags=[])
            for o in observations
        },
    )
    return compile_truth_state(
        claim_type=sky,
        truth_key=KEY,
        observations=observations,
        trust_snapshot=trust,
        policy_version=sky.policy_version,
        compile_time=EVENT,
    )


def test_three_reports_compile_to_a_sky_claim_deterministically():
    observations = [_observation(1, "few", False), _observation(2, "few", False), _observation(3, "scattered", False)]
    first, second = _compile(observations), _compile(observations)
    assert first.claim == {"cover": "few", "raining": False}
    # critical: never verified without a human vote
    assert first.status.value != "VERIFIED_TRUE"
    assert first.security.semantic_hash == second.security.semantic_hash


def test_a_clear_dry_sky_is_a_claim_too():
    state = _compile([_observation(1, "clear", False), _observation(2, "clear", False), _observation(3, "clear", False)])
    assert state.claim == {"cover": "clear", "raining": False}
