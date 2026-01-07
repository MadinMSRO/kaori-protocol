"""
Kaori Truth — Temporal Index Subsystem

Timezone-aware time handling optimized for deterministic truth compilation.
Includes temporal bucketing for TruthKey generation.

Design for extraction: This module is designed to become a standalone library
(kaori-time) in production deployments.
"""

from .normalize import (
    ensure_utc,
    to_utc,
    reject_naive,
    NaiveDatetimeError,
)
from .bucket import (
    bucket_datetime,
    parse_bucket_duration,
    BucketDuration,
    daily_bucket,
    hourly_bucket,
)
from .parse import (
    parse_datetime,
    parse_iso8601,
)
from .formats import (
    CANONICAL_DATETIME_FORMAT,
    CANONICAL_DATE_FORMAT,
    CANONICAL_BUCKET_FORMAT,
    format_canonical,
    format_bucket,
)

__all__ = [
    # Normalize
    "ensure_utc",
    "to_utc",
    "reject_naive",
    "NaiveDatetimeError",
    # Bucket
    "bucket_datetime",
    "parse_bucket_duration",
    "BucketDuration",
    "daily_bucket",
    "hourly_bucket",
    # Parse
    "parse_datetime",
    "parse_iso8601",
    # Formats
    "CANONICAL_DATETIME_FORMAT",
    "CANONICAL_DATE_FORMAT",
    "CANONICAL_BUCKET_FORMAT",
    "format_canonical",
    "format_bucket",
]
