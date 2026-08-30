#!/usr/bin/env python3
"""Authenticated 1 / retry / 2 / 3-reporter smoke against a live Kaori revision.

Requires three distinct Supabase access tokens. Does not promote traffic,
deploy Liminal, or write GCP credentials.

    export KAORI_SMOKE_URL="https://<no-traffic-revision>"
    export SMOKE_TOKEN_1 SMOKE_TOKEN_2 SMOKE_TOKEN_3
    python3 scripts/production/smoke_ledger.py

Refuse the run if the first reporter receives 200, if 202 is treated as
compiled, if evidence is not a private gs:// object, or if the 200 artifact
has no recorded vote / uses local_dev_key.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping

CLAIM_TYPE_ID = "ocean.vessel_anomaly.v1"
REQUIRED = 3
BUCKET_PREFIX = "gs://msro-kaori-observations/"
FORBIDDEN_KEY_ID = "local_dev_key"


class SmokeFailure(Exception):
    """Ledger contract was not met."""


def observation_progress(body: Mapping[str, Any]) -> tuple[int, int]:
    progress = body.get("observation_progress") or {}
    return int(progress.get("received", -1)), int(progress.get("required", -1))


def recorded_votes(body: Mapping[str, Any]) -> list[Any]:
    consensus = body.get("consensus")
    if not isinstance(consensus, dict):
        return []
    votes = consensus.get("votes")
    return votes if isinstance(votes, list) else []


def assert_pending(status: int, body: Mapping[str, Any], received: int) -> None:
    if status != 202:
        raise SmokeFailure(f"expected HTTP 202 PENDING, got {status}: {body}")
    if body.get("status") != "PENDING":
        raise SmokeFailure(f"202 body must be PENDING, got {body!r}")
    got_received, got_required = observation_progress(body)
    if got_received != received or got_required != REQUIRED:
        raise SmokeFailure(
            f"observation_progress expected received={received} required={REQUIRED}, "
            f"got received={got_received} required={got_required}"
        )


def assert_compiled(status: int, body: Mapping[str, Any]) -> None:
    if status != 200:
        raise SmokeFailure(f"expected HTTP 200 TruthState, got {status}: {body}")
    if body.get("truthkey") in (None, ""):
        raise SmokeFailure("200 body must include truthkey")
    key_id = (body.get("security") or {}).get("key_id")
    if key_id == FORBIDDEN_KEY_ID:
        raise SmokeFailure("security.key_id must not be local_dev_key")
    votes = recorded_votes(body)
    if not votes:
        raise SmokeFailure(
            "200 TruthState has no consensus.votes — KAORI_GENERALIST_URL is "
            "missing or the vote was not recorded"
        )
    compile_inputs = body.get("compile_inputs") or {}
    observations = compile_inputs.get("observations") or []
    if len(observations) < REQUIRED:
        raise SmokeFailure(
            f"200 artifact must compile the full ledger (>= {REQUIRED} observations), "
            f"got {len(observations)}"
        )


def assert_evidence_ref(ref: Mapping[str, Any]) -> None:
    uri = str(ref.get("uri") or "")
    sha256 = str(ref.get("sha256") or "")
    if not uri.startswith(BUCKET_PREFIX):
        raise SmokeFailure(f"evidence uri must be private {BUCKET_PREFIX}..., got {uri!r}")
    if len(sha256) != 64:
        raise SmokeFailure(f"evidence sha256 must be 64 hex chars, got {sha256!r}")


def smoke_truth_key() -> str:
    stamp = time.strftime("%Y-%m-%dT%H:00Z", time.gmtime())
    cell = os.environ.get("SMOKE_H3_CELL", "smokeledgercell")
    return f"ocean:vessel_anomaly:h3:{cell}:surface:{stamp}"


def _request(
    url: str,
    *,
    token: str,
    method: str = "GET",
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 30,
) -> tuple[int, dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
            return int(response.status), body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        try:
            body = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            body = {"detail": raw or str(exc)}
        return int(exc.code), body


def upload_evidence(base_url: str, token: str, content: bytes, filename: str) -> dict[str, Any]:
    expected = hashlib.sha256(content).hexdigest()
    boundary = f"----kaoriSmoke{uuid.uuid4().hex}"
    parts = [
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="expected_sha256"\r\n\r\n'
        f"{expected}\r\n".encode(),
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + content
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    status, body = _request(
        f"{base_url}/v1/evidence",
        token=token,
        method="POST",
        data=b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    if status != 200:
        raise SmokeFailure(f"POST /v1/evidence expected 200, got {status}: {body}")
    assert_evidence_ref(body)
    if body.get("sha256") != expected:
        raise SmokeFailure("evidence sha256 does not match uploaded bytes")
    return body


def compile_observation(
    base_url: str,
    token: str,
    truth_key: str,
    refs: list[dict[str, Any]],
    observation_id: str,
    *,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    payload = {
        "truth_key": truth_key,
        "claim_type_id": CLAIM_TYPE_ID,
        "observations": [
            {
                "observation_id": observation_id,
                "claim_type": CLAIM_TYPE_ID,
                "reported_at": "2026-01-07T12:00:00Z",
                "geo": {"lat": -8.3405, "lon": 115.0920},
                "payload": {
                    "observation_duration_min": 15,
                    "vessels": [{"id": "smoke-1"}],
                },
                "evidence_refs": refs,
            }
        ],
    }
    return _request(
        f"{base_url}/v1/compile",
        token=token,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        timeout=timeout,
    )


def reporter_bundle(base_url: str, token: str, label: str) -> list[dict[str, Any]]:
    photo = upload_evidence(base_url, token, f"photo-{label}-{time.time_ns()}".encode(), f"{label}.jpg")
    context = upload_evidence(
        base_url, token, f"context-{label}-{time.time_ns()}".encode(), f"{label}-context.jpg"
    )
    return [photo, context]


def run_smoke(base_url: str, tokens: tuple[str, str, str]) -> str:
    truth_key = os.environ.get("SMOKE_TRUTH_KEY") or smoke_truth_key()
    compile_timeout = float(os.environ.get("SMOKE_COMPILE_TIMEOUT", "150"))
    first, second, third = tokens

    print(f"truth_key={truth_key}")
    print("reporter 1: evidence + compile")
    refs_1 = reporter_bundle(base_url, first, "r1")
    status, body = compile_observation(
        base_url, first, truth_key, refs_1, str(uuid.uuid4()), timeout=30
    )
    assert_pending(status, body, 1)

    print("reporter 1 retry: same identity, new observation id")
    status, body = compile_observation(
        base_url, first, truth_key, refs_1, str(uuid.uuid4()), timeout=30
    )
    assert_pending(status, body, 1)

    print("reporter 2: evidence + compile")
    refs_2 = reporter_bundle(base_url, second, "r2")
    status, body = compile_observation(
        base_url, second, truth_key, refs_2, str(uuid.uuid4()), timeout=30
    )
    assert_pending(status, body, 2)

    print("reporter 3: evidence + compile (waits for recorded vote)")
    refs_3 = reporter_bundle(base_url, third, "r3")
    status, body = compile_observation(
        base_url, third, truth_key, refs_3, str(uuid.uuid4()), timeout=compile_timeout
    )
    assert_compiled(status, body)
    print("smoke passed: 202/202/202/200 with recorded vote on the full ledger")
    return truth_key


def main(argv: list[str] | None = None) -> int:
    del argv
    base_url = os.environ.get("KAORI_SMOKE_URL", "").rstrip("/")
    tokens = (
        os.environ.get("SMOKE_TOKEN_1", ""),
        os.environ.get("SMOKE_TOKEN_2", ""),
        os.environ.get("SMOKE_TOKEN_3", ""),
    )
    if not base_url:
        print("KAORI_SMOKE_URL is required", file=sys.stderr)
        return 2
    if any(not token for token in tokens) or len(set(tokens)) != 3:
        print("SMOKE_TOKEN_1/2/3 must be three distinct Supabase access tokens", file=sys.stderr)
        return 2
    try:
        run_smoke(base_url, tokens)
    except SmokeFailure as exc:
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
