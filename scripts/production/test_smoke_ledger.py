"""Unit checks for smoke_ledger assertions — no network, no GCP."""
from __future__ import annotations

import unittest

from smoke_ledger import (
    SmokeFailure,
    assert_compiled,
    assert_evidence_ref,
    assert_pending,
)


class SmokeAssertionTests(unittest.TestCase):
    def test_pending_accepts_202_progress(self) -> None:
        assert_pending(
            202,
            {"status": "PENDING", "observation_progress": {"received": 1, "required": 3}},
            1,
        )

    def test_pending_rejects_200(self) -> None:
        with self.assertRaises(SmokeFailure):
            assert_pending(200, {"truthkey": "k"}, 1)

    def test_compiled_requires_votes_and_full_ledger(self) -> None:
        with self.assertRaises(SmokeFailure):
            assert_compiled(200, {"truthkey": "k", "consensus": {"votes": []}})
        assert_compiled(
            200,
            {
                "truthkey": "k",
                "security": {"key_id": "msro-kaori-prod-1"},
                "consensus": {"votes": [{"type": "VALIDATION_VOTE"}]},
                "compile_inputs": {"observations": [{}, {}, {}]},
            },
        )

    def test_compiled_rejects_dev_key(self) -> None:
        with self.assertRaises(SmokeFailure):
            assert_compiled(
                200,
                {
                    "truthkey": "k",
                    "security": {"key_id": "local_dev_key"},
                    "consensus": {"votes": [{}]},
                    "compile_inputs": {"observations": [{}, {}, {}]},
                },
            )

    def test_evidence_must_be_private_bucket(self) -> None:
        assert_evidence_ref(
            {
                "uri": "gs://msro-kaori-observations/observations/aa/bb/c.jpg",
                "sha256": "a" * 64,
            }
        )
        with self.assertRaises(SmokeFailure):
            assert_evidence_ref(
                {"uri": "https://example.test/c.jpg", "sha256": "a" * 64}
            )


if __name__ == "__main__":
    unittest.main()
