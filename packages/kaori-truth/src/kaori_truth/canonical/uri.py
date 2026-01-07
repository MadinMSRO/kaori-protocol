"""
Kaori Truth — Canonical URI Normalization

URI and evidence reference canonicalization for deterministic references.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def normalize_scheme(scheme: str) -> str:
    """Normalize URI scheme to lowercase."""
    return scheme.lower()


def normalize_host(host: str) -> str:
    """Normalize host to lowercase."""
    return host.lower() if host else ""


def normalize_path(path: str) -> str:
    """
    Normalize URI path.
    
    - Remove trailing slashes (except for root)
    - Collapse double slashes
    """
    if not path:
        return "/"
    
    # Collapse double slashes
    path = re.sub(r'/+', '/', path)
    
    # Remove trailing slash (keep root /)
    if len(path) > 1 and path.endswith('/'):
        path = path.rstrip('/')
    
    return path


def normalize_query(query: str) -> str:
    """
    Normalize query string.
    
    - Sort parameters by key
    - Normalize encoding
    """
    if not query:
        return ""
    
    # Parse and sort
    params = parse_qsl(query, keep_blank_values=True)
    params.sort(key=lambda x: (x[0], x[1]))
    
    return urlencode(params)


def canonical_uri(uri: str) -> str:
    """
    Canonicalize a URI for deterministic comparison.
    
    Rules:
    1. Scheme lowercase
    2. Host lowercase
    3. Remove trailing slashes from path (except root)
    4. Collapse double slashes in path
    5. Sort query parameters
    6. Remove fragment (for content identity)
    
    Args:
        uri: The URI to canonicalize
        
    Returns:
        Canonical URI string
    """
    parsed = urlparse(uri)
    
    canonical = urlunparse((
        normalize_scheme(parsed.scheme),
        normalize_host(parsed.netloc),
        normalize_path(parsed.path),
        parsed.params,  # Keep as-is
        normalize_query(parsed.query),
        "",  # Remove fragment for canonical identity
    ))
    
    return canonical


def normalize_evidence_ref(ref: str) -> str:
    """
    Normalize an evidence reference URI.
    
    Special handling for common evidence storage schemes:
    - gs:// (Google Cloud Storage)
    - s3:// (Amazon S3)
    - file:// (Local file)
    - https:// (HTTP)
    
    Args:
        ref: The evidence reference URI
        
    Returns:
        Canonical evidence reference
    """
    ref = ref.strip()
    
    # Handle gs:// and s3:// specially (case-sensitive bucket names on some systems)
    if ref.startswith(('gs://', 's3://')):
        scheme = ref[:5] if ref.startswith('gs://') else ref[:5]
        rest = ref[5:]
        
        # Normalize path only
        if '/' in rest:
            bucket, path = rest.split('/', 1)
            path = normalize_path('/' + path).lstrip('/')
            return f"{scheme}{bucket}/{path}" if path else f"{scheme}{bucket}"
        return ref
    
    # Standard URI canonicalization for other schemes
    return canonical_uri(ref)


def validate_evidence_hash(hash_str: str) -> bool:
    """
    Validate an evidence hash string.
    
    Must be lowercase hex SHA256 (64 characters).
    
    Args:
        hash_str: The hash string to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not hash_str:
        return False
    return bool(re.match(r'^[a-f0-9]{64}$', hash_str))


def canonical_evidence_hash(hash_str: str) -> str:
    """
    Canonicalize an evidence hash.
    
    Rules:
    1. Lowercase
    2. No prefix (remove 0x if present)
    
    Args:
        hash_str: The hash string to canonicalize
        
    Returns:
        Canonical hash string
        
    Raises:
        ValueError: If hash is invalid
    """
    hash_str = hash_str.lower()
    
    # Remove 0x prefix if present
    if hash_str.startswith('0x'):
        hash_str = hash_str[2:]
    
    if not validate_evidence_hash(hash_str):
        raise ValueError(f"Invalid evidence hash: {hash_str}")
    
    return hash_str
