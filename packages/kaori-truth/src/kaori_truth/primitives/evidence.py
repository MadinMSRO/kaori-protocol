"""
Kaori Truth — EvidenceRef Primitive

Canonical evidence reference with content-binding.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from kaori_truth.canonical.uri import canonical_uri, normalize_evidence_ref, canonical_evidence_hash
from kaori_truth.canonical.hash import canonical_hash


class EvidenceRef(BaseModel):
    """
    Canonical evidence reference with content-binding.
    
    Evidence identity is determined by sha256 hash, not URI.
    The URI is a non-canonical pointer to where the content can be fetched.
    
    Per protocol requirements, EvidenceRef MUST include a content hash
    for adversarial auditability.
    """
    uri: str  # Non-canonical pointer (GCS, S3, HTTP, file://)
    sha256: str  # Canonical identity (lowercase hex)
    mime_type: Optional[str] = None
    bytes_size: Optional[int] = None
    capture_time: Optional[datetime] = None
    
    @field_validator('sha256')
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        """Validate and canonicalize SHA256 hash."""
        return canonical_evidence_hash(v)
    
    @field_validator('uri')
    @classmethod
    def normalize_uri(cls, v: str) -> str:
        """Normalize URI for storage (not full canonicalization)."""
        return normalize_evidence_ref(v)
    
    def canonical(self) -> dict:
        """
        Get canonical representation for hashing.
        
        Only includes fields that define identity.
        """
        result = {
            "sha256": self.sha256,
            "uri": canonical_uri(self.uri),
        }
        if self.mime_type:
            result["mime_type"] = self.mime_type.lower()
        if self.capture_time:
            from kaori_truth.canonical.datetime import canonical_datetime
            result["capture_time"] = canonical_datetime(self.capture_time)
        return result
    
    def hash(self) -> str:
        """Compute canonical hash of this evidence ref."""
        return canonical_hash(self.canonical())
    
    @classmethod
    def from_content(
        cls,
        content: bytes,
        uri: str,
        *,
        mime_type: Optional[str] = None,
        capture_time: Optional[datetime] = None,
    ) -> "EvidenceRef":
        """
        Create EvidenceRef from content bytes.
        
        Computes SHA256 hash from content.
        
        Args:
            content: The evidence content bytes
            uri: Where the content is/will be stored
            mime_type: MIME type of the content
            capture_time: When the evidence was captured
            
        Returns:
            EvidenceRef with computed hash
        """
        import hashlib
        sha256 = hashlib.sha256(content).hexdigest()
        
        return cls(
            uri=uri,
            sha256=sha256,
            mime_type=mime_type,
            bytes_size=len(content),
            capture_time=capture_time,
        )


def canonical_evidence_ref(ref: EvidenceRef) -> dict:
    """
    Get canonical representation of an EvidenceRef.
    
    Args:
        ref: The EvidenceRef to canonicalize
        
    Returns:
        Canonical dictionary representation
    """
    return ref.canonical()
