"""Private kaori-api to kaori-generalist invocation and vote recording."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.request
from typing import Callable, List, Optional
from urllib.parse import urlencode

from kaori_flow import FlowCore
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.primitives.observation import Observation

from kaori_api.generalist import (
    ValidationVote,
    ValidatorRequest,
    canonical_timestamp,
    log_validation_vote,
    validator_signing_key,
    verify_validation_vote,
)
from kaori_api.validation import GENERALIST_AGENT_ID, record_validation_vote

LOGGER = logging.getLogger(__name__)
GENERALIST_URL_ENV = "KAORI_GENERALIST_URL"
GCP_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/identity"
)
# ISO-8601 duration on ai_validation_routing.generalist.timeout (new field).
_GENERALIST_TIMEOUT_RE = re.compile(
    r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$"
)


def iso8601_duration_seconds(value: str) -> float:
    """Parse ClaimType generalist.timeout. Does not default to 30s."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ai_validation_routing.generalist.timeout is required")
    raw = value.strip().upper()
    match = _GENERALIST_TIMEOUT_RE.fullmatch(raw)
    if not match or raw == "PT":
        raise ValueError(
            "ai_validation_routing.generalist.timeout must be an ISO-8601 duration "
            f"such as PT2M or PT90S, got {value!r}"
        )
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = float(match.group(3) or 0)
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise ValueError("ai_validation_routing.generalist.timeout must be > 0")
    return total


def generalist_timeout_seconds(claim_type) -> float:
    """
    Read ai_validation_routing.generalist.timeout from the loaded ClaimType.

    This field is new because live YAML had no CLIP wait (only dispute
    PT12H/PT24H/PT48H, which must not be reused). Never fall back to 30s.
    """
    config = claim_type.get_config() if hasattr(claim_type, "get_config") else {}
    routing = (config or {}).get("ai_validation_routing") or {}
    generalist = routing.get("generalist") or {}
    raw = generalist.get("timeout")
    return iso8601_duration_seconds(raw)


def votes_for_truthkey(flow: FlowCore, truthkey_id: str) -> list:
    return [
        signal
        for signal in flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
        if signal.object_id == truthkey_id
    ]


class GeneralistClient:
    """Invoke the IAM-protected generalist service with a Cloud Run ID token."""

    def __init__(
        self,
        url: str,
        *,
        token_provider: Optional[Callable[[str], str]] = None,
        signing_key: Optional[bytes] = None,
    ):
        self.url = url.rstrip("/")
        self.token_provider = token_provider or cloud_run_id_token
        self.signing_key = signing_key or validator_signing_key()

    @classmethod
    def from_env(cls) -> Optional["GeneralistClient"]:
        url = os.environ.get(GENERALIST_URL_ENV)
        return None if not url else cls(url)

    def validate(
        self,
        *,
        truthkey_id: str,
        claim_type_id: str,
        observations: List[Observation],
        timeout: float,
        on_late_vote: Optional[Callable[[ValidationVote], None]] = None,
    ) -> ValidationVote:
        if timeout is None:
            raise ValueError("generalist timeout must come from ClaimType YAML")
        wait = float(timeout)
        if wait <= 0:
            raise ValueError("generalist timeout must come from ClaimType YAML")
        self.last_timeout = wait
        payload = ValidatorRequest(
            truthkey_id=truthkey_id,
            claim_type_id=claim_type_id,
            observations=observations,
            evidence_refs=[
                ref
                for observation in observations
                for ref in observation.evidence_refs
            ],
        )
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload.model_dump(mode="json")).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token_provider(self.url)}",
                "Content-Type": "application/json",
            },
        )
        box: dict = {}
        done = threading.Event()

        def read_body() -> None:
            try:
                # YAML timeout is the declared wait (never 30s). The socket is
                # not closed at that deadline so a late generalist 200 is still
                # read and recorded.
                with urllib.request.urlopen(request, timeout=None) as response:
                    box["vote"] = ValidationVote.model_validate_json(response.read())
            except Exception as exc:
                box["error"] = exc
            finally:
                done.set()

        reader = threading.Thread(target=read_body, name="kaori-generalist-http")
        reader.start()
        finished_in_budget = done.wait(wait)
        if finished_in_budget:
            if "vote" in box:
                self._validate_vote(box["vote"], truthkey_id)
                return box["vote"]
            raise box.get("error") or TimeoutError(
                "generalist exceeded ClaimType timeout"
            )

        def finish_late() -> None:
            done.wait()
            if "vote" not in box:
                return
            try:
                self._validate_vote(box["vote"], truthkey_id)
            except Exception:
                LOGGER.exception(
                    "late generalist vote failed validation for truthkey %s",
                    truthkey_id,
                )
                return
            if on_late_vote:
                on_late_vote(box["vote"])

        threading.Thread(
            target=finish_late,
            name=f"kaori-generalist-late-{truthkey_id}",
            daemon=False,
        ).start()
        raise TimeoutError("generalist exceeded ClaimType timeout")

    def _validate_vote(self, vote: ValidationVote, truthkey_id: str) -> None:
        if vote.agent_id != GENERALIST_AGENT_ID:
            raise ValueError("generalist response has an unexpected agent_id")
        if vote.truthkey_id != truthkey_id:
            raise ValueError("generalist response has an unexpected truthkey_id")
        if vote.window_id != f"window:{truthkey_id}":
            raise ValueError("generalist response has an unexpected window_id")
        if not verify_validation_vote(vote, self.signing_key):
            raise ValueError("generalist response has an invalid signature")


def cloud_run_id_token(audience: str) -> str:
    """Mint an ID token from the Cloud Run metadata server."""
    url = f"{GCP_IDENTITY_URL}?{urlencode({'audience': audience, 'format': 'full'})}"
    request = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=10.0) as response:
        return response.read().decode("utf-8")


def vote_as_compiler_record(vote: ValidationVote) -> dict:
    """
    Compiler input: FLOW_SPEC ValidationSignal fields plus signal_type.

    Lands on TruthState.consensus.votes. vote_type stays RATIFY/REJECT
    for compute_consensus. Signature is omitted (not an artifact secret).
    """
    record = {
        "agent_id": vote.agent_id,
        "truthkey_id": vote.truthkey_id,
        "window_id": vote.window_id,
        "vote": vote.vote,
        "vote_type": vote.vote,
        "confidence": vote.confidence,
        "timestamp": canonical_timestamp(vote.timestamp),
        "signal_type": SignalTypes.VALIDATION_VOTE,
    }
    return {key: value for key, value in record.items() if value is not None}


def _record_vote(flow: FlowCore, vote: ValidationVote) -> ValidationVote:
    log_validation_vote(vote, source="kaori-api")
    record_validation_vote(
        flow,
        agent_id=vote.agent_id,
        truthkey_id=vote.truthkey_id,
        window_id=vote.window_id,
        vote=vote.vote,
        confidence=vote.confidence,
        time=vote.timestamp,
        signature=vote.signature,
    )
    return vote


def validate_and_record_vote(
    *,
    client: GeneralistClient,
    flow: FlowCore,
    truthkey_id: str,
    claim_type_id: str,
    observations: List[Observation],
    timeout: float,
) -> ValidationVote:
    """
    Invoke the private generalist, then write its signed vote.

    Does not compile. TimeoutError is not swallowed — the caller must not
    compile as if CLIP ran. A late 200 is still recorded.
    """

    def record_late(vote: ValidationVote) -> None:
        _record_vote(flow, vote)

    vote = client.validate(
        truthkey_id=truthkey_id,
        claim_type_id=claim_type_id,
        observations=observations,
        timeout=timeout,
        on_late_vote=record_late,
    )
    return _record_vote(flow, vote)


def start_validate_and_record(
    *,
    client: GeneralistClient,
    flow: FlowCore,
    truthkey_id: str,
    claim_type_id: str,
    observations: List[Observation],
    timeout: float,
    on_vote: Callable[[ValidationVote], None],
    on_timeout: Optional[Callable[[], None]] = None,
    on_error: Optional[Callable[[BaseException], None]] = None,
) -> threading.Thread:
    """
    Observe/record stays async internally. HTTP compile waits for on_vote
    or on_timeout. A late generalist 200 still records VALIDATION_VOTE
    without compiling after a YAML timeout.
    """

    def run() -> None:
        try:
            vote = validate_and_record_vote(
                client=client,
                flow=flow,
                truthkey_id=truthkey_id,
                claim_type_id=claim_type_id,
                observations=observations,
                timeout=timeout,
            )
            on_vote(vote)
        except TimeoutError:
            LOGGER.exception(
                "kaori-generalist exceeded ClaimType timeout for truthkey %s; "
                "not compiling without a vote",
                truthkey_id,
            )
            if on_timeout:
                on_timeout()
        except Exception as exc:
            LOGGER.exception("kaori-generalist failed for truthkey %s", truthkey_id)
            if on_error:
                on_error(exc)

    thread = threading.Thread(
        target=run,
        name=f"kaori-generalist-{truthkey_id}",
        daemon=False,
    )
    thread.start()
    return thread


def validate_persisted_truth_state(
    *,
    client: GeneralistClient,
    flow: FlowCore,
    truthkey_id: str,
    claim_type_id: str,
    observations: List[Observation],
    timeout: float,
) -> Optional[ValidationVote]:
    """Backward-compatible name. Validation remains observe → validate → compile."""
    return validate_and_record_vote(
        client=client,
        flow=flow,
        truthkey_id=truthkey_id,
        claim_type_id=claim_type_id,
        observations=observations,
        timeout=timeout,
    )
