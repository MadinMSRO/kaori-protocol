"""ClaimTypes a published timetable can address.

The compiler is unchanged. A TruthKey is the ClaimType bucket of the
timetable event, never a human window.
"""
from __future__ import annotations

import hashlib
import json
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
EVENT = datetime(2026, 9, 24, 5, 11, 40, tzinfo=timezone.utc)
LOCATION = {"lat": 4.175, "lon": 73.509}

# Space resolution is NSIDE. The compiler passes it through unchanged.
TYPES = {
    "space/satellite_pass_v1.yaml": ("space", "satellite_pass", "healpix", 64, "orbital_shell", "PT1H", "2026-09-24T05:00Z"),
    "space/asteroid_occultation_v1.yaml": ("space", "asteroid_occultation", "healpix", 64, "sky", "PT1H", "2026-09-24T05:00Z"),
    "space/lunar_occultation_v1.yaml": ("space", "lunar_occultation", "healpix", 64, "sky", "PT1H", "2026-09-24T05:00Z"),
    "earth/sentinel2_scene_v1.yaml": ("earth", "sentinel2_scene", "h3", 6, "surface", "PT1H", "2026-09-24T05:00Z"),
    "ocean/sentinel2_water_v1.yaml": ("ocean", "sentinel2_water", "h3", 6, "surface", "PT1H", "2026-09-24T05:00Z"),
    "ocean/sentinel3_olci_v1.yaml": ("ocean", "sentinel3_olci", "h3", 5, "surface", "PT1H", "2026-09-24T05:00Z"),
    "earth/sentinel1_sar_v1.yaml": ("earth", "sentinel1_sar", "h3", 6, "surface", "PT1H", "2026-09-24T05:00Z"),
}

# Required observation fields. Same names the timetable cockpit sends.
OBSERVATION_FIELDS = {
    "space/satellite_pass_v1.yaml": ["bearing", "first_visible", "last_visible", "max_elevation"],
    "space/asteroid_occultation_v1.yaml": ["asteroid", "star", "disappeared"],
    "space/lunar_occultation_v1.yaml": ["star", "disappearance_utc", "seen"],
    "earth/sentinel2_scene_v1.yaml": ["granule", "surface", "ground"],
    "ocean/sentinel2_water_v1.yaml": ["granule", "water", "clarity"],
    "ocean/sentinel3_olci_v1.yaml": ["granule", "colour"],
    "earth/sentinel1_sar_v1.yaml": ["granule", "surface", "roughness"],
}

# Existing space contracts that were still addressed with H3.
SPACE_SPATIAL_FIXES = (
    "space/debris_track_v1.yaml",
    "space/light_pollution_v1.yaml",
)


def _load(name: str):
    return load_claim_type(ROOT / name)


def test_timetable_types_set_an_explicit_floor_and_an_hour_bucket():
    for name, (domain, topic, spatial, resolution, z_index, duration, bucket) in TYPES.items():
        claim_type = _load(name)
        assert claim_type.domain == domain
        assert claim_type.topic == topic
        assert claim_type.truthkey.spatial_system == spatial
        assert claim_type.truthkey.resolution == resolution
        assert claim_type.truthkey.z_index == z_index
        assert claim_type.truthkey.time_bucket == duration
        assert claim_type.minimum_observations() == 3
        claim_type.validate_domain_config()
        fields = [
            field["name"]
            for field in claim_type.get_config()["ui_schema"]["fields"]
            if field.get("required")
        ]
        assert fields == OBSERVATION_FIELDS[name]
        assert list(claim_type.output_schema["properties"]) == fields
        implicit = claim_type.get_config()["implicit_consensus"]
        assert implicit["enabled"] is True
        assert implicit["min_observations"] == 3
        sky = spatial == "healpix"
        key = build_truthkey(
            claim_type_id=claim_type.id,
            event_time=EVENT,
            spatial_system=spatial,
            spatial_resolution=resolution,
            z_index=z_index,
            location={"ra": 247.3515, "dec": -26.432} if sky else LOCATION,
            time_bucket_duration=duration,
        )
        parts = parse_truthkey(key)
        assert parts.domain == domain
        assert parts.topic == topic
        assert parts.spatial_system == spatial
        assert parts.time_bucket == bucket
        if sky:
            assert ":h3:" not in key
            if parts.spatial_id.isdigit():
                assert parts.spatial_id == "35632"
        else:
            assert parts.spatial_system == "h3"
        assert "48 hours" not in key
        assert "hour" not in parts.time_bucket


def test_sentinel_scene_compiles_the_ground_not_the_plan():
    claim_type = _load("earth/sentinel2_scene_v1.yaml")
    payload = {"granule": "S2A_T43NCE", "surface": "shore", "ground": "sand and scrub"}
    observation = Observation(
        observation_id=UUID("11111111-1111-1111-1111-111111111111"),
        claim_type=claim_type.id,
        reported_at=EVENT,
        reporter_id="user:observer-1",
        reporter_context=ReporterContext(standing=Standing.SILVER, trust_score=0.75, source_type="human"),
        geo={"lat": LOCATION["lat"], "lon": LOCATION["lon"]},
        payload=payload,
        evidence_refs=[EvidenceRef(uri="gs://kaori-evidence/shore.jpg", sha256="a" * 64)],
    )
    trust = TrustSnapshot.create(
        snapshot_id="snapshot-timetable",
        snapshot_time=EVENT,
        agent_trusts={
            "user:observer-1": AgentTrust(
                agent_id="user:observer-1",
                effective_trust=150.0,
                standing=150.0,
                derived_class="silver",
                flags=[],
            )
        },
    )
    first = compile_truth_state(
        claim_type=claim_type,
        truth_key="earth:sentinel2_scene:h3:abc:surface:2026-09-24T05:00Z",
        observations=[observation],
        trust_snapshot=trust,
        policy_version=claim_type.policy_version,
        compile_time=EVENT,
    )
    second = compile_truth_state(
        claim_type=claim_type,
        truth_key="earth:sentinel2_scene:h3:abc:surface:2026-09-24T05:00Z",
        observations=[observation],
        trust_snapshot=trust,
        policy_version=claim_type.policy_version,
        compile_time=EVENT,
    )
    assert first.claim == payload
    assert "acquisition_true" not in first.claim
    assert first.security.semantic_hash == second.security.semantic_hash


def test_space_contracts_use_healpix_and_the_lock_matches_the_files():
    for name in SPACE_SPATIAL_FIXES:
        claim_type = _load(name)
        assert claim_type.domain == "space"
        assert claim_type.truthkey.spatial_system == "healpix"
        assert claim_type.truthkey.resolution == 64
        claim_type.validate_domain_config()

    repo = Path(__file__).resolve().parents[3]
    lock = json.loads((repo / "packages" / "kaori-spec" / "claimtype.lock.json").read_text(encoding="utf-8"))
    locked = lock["locked"]
    expected = [
        f"packages/kaori-spec/schemas/{name}"
        for name in (*TYPES, *SPACE_SPATIAL_FIXES, "earth/nakaiy_v1.yaml")
    ]
    assert set(locked) == set(expected)
    for rel in expected:
        text = (repo / rel).read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert locked[rel]["sha256"] == digest
