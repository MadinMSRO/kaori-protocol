"""
Kaori Truth — Canonical String Normalization

Unicode and whitespace normalization for deterministic serialization.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_unicode(s: str) -> str:
    """
    Normalize a string to NFC (Canonical Decomposition, followed by Canonical Composition).
    
    This ensures that equivalent Unicode sequences are represented identically.
    For example, 'é' (U+00E9) and 'e' + '◌́' (U+0065 + U+0301) become identical.
    
    Args:
        s: The string to normalize
        
    Returns:
        NFC-normalized string
    """
    return unicodedata.normalize("NFC", s)


def normalize_whitespace(s: str) -> str:
    """
    Normalize whitespace: trim and collapse internal whitespace to single spaces.
    
    Args:
        s: The string to normalize
        
    Returns:
        Whitespace-normalized string
    """
    # Trim leading/trailing
    s = s.strip()
    # Collapse internal whitespace
    s = re.sub(r'\s+', ' ', s)
    return s


def canonical_string(s: str, *, trim: bool = True, collapse_whitespace: bool = True) -> str:
    """
    Canonicalize a string for deterministic serialization.
    
    Applies:
    1. NFC unicode normalization
    2. Optional whitespace trimming
    3. Optional whitespace collapse
    
    Args:
        s: The string to canonicalize
        trim: Whether to trim leading/trailing whitespace
        collapse_whitespace: Whether to collapse internal whitespace
        
    Returns:
        Canonical string
    """
    # NFC normalization
    s = normalize_unicode(s)
    
    # Whitespace normalization
    if trim:
        s = s.strip()
    if collapse_whitespace:
        s = re.sub(r'\s+', ' ', s)
    
    return s


# Allowed characters for canonical identifiers
# Recommend: [a-z0-9._-]
CANONICAL_ID_PATTERN = re.compile(r'^[a-z0-9._-]+$')


def validate_canonical_id(id_str: str) -> bool:
    """
    Validate that a string conforms to canonical ID requirements.
    
    Canonical IDs must contain only: a-z, 0-9, '.', '_', '-'
    
    Args:
        id_str: The ID string to validate
        
    Returns:
        True if valid, False otherwise
    """
    return bool(CANONICAL_ID_PATTERN.match(id_str))


def to_canonical_id(s: str) -> str:
    """
    Convert a string to a canonical ID.
    
    Applies:
    1. Lowercase
    2. Replace spaces and invalid chars with '_'
    3. Collapse multiple '_' to single
    4. Strip leading/trailing '_'
    
    Args:
        s: The string to convert
        
    Returns:
        Canonical ID string
        
    Raises:
        ValueError: If the resulting ID is empty
    """
    # Lowercase
    s = s.lower()
    # Replace invalid chars with underscore
    s = re.sub(r'[^a-z0-9._-]', '_', s)
    # Collapse multiple underscores
    s = re.sub(r'_+', '_', s)
    # Strip leading/trailing underscores
    s = s.strip('_')
    
    if not s:
        raise ValueError("Canonical ID cannot be empty")
    
    return s
