"""Private kaori-api to kaori-bouncer invocation and vote recording."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Callable, List, Optional
from urllib.parse import urlencode

from kaori_flow import FlowCore
from kaori_truth.primitives.observation import Observation

from kaori_api.bouncer import (
    CORAL_CLAIM_TYPE,
    BouncerRequest,
    ValidationVote,
    bouncer_signing_key,
    verify_validation_vote,
)
from kaori_api.validation import BOUNCER_AGENT_ID, record_validation_vote

LOGGER = logging.getLogger(__name__)
BOUNCER_URL_ENV = "KAORI_BOUNCER_URL"
GCP_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/identity"
)


class BouncerClient:
    """Invoke the IAM-protected bouncer service with a Cloud Run ID token."""

    def __init__(
        self,
        url: str,
        *,
        token_provider: Optional[Callable[[str], str]] = None,
        signing_key: Optional[bytes] = None,
        timeout: float = 30.0,
    ):
        self.url = url.rstrip("/")
        self.token_provider = token_provider or cloud_run_id_token
        self.signing_key = signing_key or bouncer_signing_key()
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> Optional["BouncerClient"]:
        url = os.environ.get(BOUNCER_URL_ENV)
        return None if not url else cls(url)

    def validate(
        self,
        *,
        truthkey_id: str,
        claim_type_id: str,
        observations: List[Observation],
    ) -> ValidationVote:
        payload = BouncerRequest(
            truthkey_id=truthkey_id,
            claim_type_id=claim_type_id,
            observations=observations,
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
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            vote = ValidationVote.model_validate_json(response.read())
        self._validate_vote(vote, truthkey_id)
        return vote

    def _validate_vote(self, vote: ValidationVote, truthkey_id: str) -> None:
        if vote.agent_id != BOUNCER_AGENT_ID:
            raise ValueError("bouncer response has an unexpected agent_id")
        if vote.truthkey_id != truthkey_id:
            raise ValueError("bouncer response has an unexpected truthkey_id")
        if vote.window_id != f"window:{truthkey_id}":
            raise ValueError("bouncer response has an unexpected window_id")
        if not verify_validation_vote(vote, self.signing_key):
            raise ValueError("bouncer response has an invalid signature")


def cloud_run_id_token(audience: str) -> str:
    """Mint an ID token from the Cloud Run metadata server."""
    url = f"{GCP_IDENTITY_URL}?{urlencode({'audience': audience, 'format': 'full'})}"
    request = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=10.0) as response:
        return response.read().decode("utf-8")


def validate_persisted_truth_state(
    *,
    client: BouncerClient,
    flow: FlowCore,
    truthkey_id: str,
    claim_type_id: str,
    observations: List[Observation],
) -> None:
    """
    Post-persist worker: invoke the separate runner, then write its signed vote.

    Errors are logged because validation must never change the compile response.
    """
    if claim_type_id != CORAL_CLAIM_TYPE:
        return
    try:
        vote = client.validate(
            truthkey_id=truthkey_id,
            claim_type_id=claim_type_id,
            observations=observations,
        )
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
    except Exception:
        LOGGER.exception("kaori-bouncer failed for truthkey %s", truthkey_id)
