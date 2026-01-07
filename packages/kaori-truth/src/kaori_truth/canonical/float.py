"""
Kaori Truth — Canonical Float Serialization

Float quantization for deterministic serialization across runtimes.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union


# Default quantization precision (1e-6 = 6 decimal places)
DEFAULT_PRECISION = 6


def quantize_float(
    value: Union[float, int, Decimal],
    precision: int = DEFAULT_PRECISION,
) -> Decimal:
    """
    Quantize a float to a fixed number of decimal places.
    
    This ensures consistent representation across different runtimes
    that may have different float formatting behaviors.
    
    Args:
        value: The numeric value to quantize
        precision: Number of decimal places (default: 6)
        
    Returns:
        Decimal quantized to the specified precision
    """
    if isinstance(value, int):
        value = float(value)
    
    if isinstance(value, float):
        # Convert to Decimal via string to avoid float precision issues
        value = Decimal(str(value))
    
    # Create quantization template (e.g., "0.000001" for precision=6)
    quantize_template = Decimal(10) ** -precision
    
    return value.quantize(quantize_template, rounding=ROUND_HALF_UP)


def canonical_float(
    value: Union[float, int, Decimal],
    precision: int = DEFAULT_PRECISION,
) -> str:
    """
    Convert a float to its canonical string representation.
    
    Rules:
    1. Quantize to fixed precision
    2. Remove trailing zeros after decimal point
    3. Remove decimal point if no decimals remain
    4. Handle special cases: 0 -> "0", -0 -> "0"
    
    Args:
        value: The numeric value to canonicalize
        precision: Number of decimal places (default: 6)
        
    Returns:
        Canonical string representation
    """
    if value is None:
        raise ValueError("Cannot canonicalize None as float")
    
    # Handle special cases
    if isinstance(value, float):
        if value != value:  # NaN check
            raise ValueError("Cannot canonicalize NaN")
        if value == float('inf') or value == float('-inf'):
            raise ValueError("Cannot canonicalize infinity")
    
    # Quantize
    quantized = quantize_float(value, precision)
    
    # Handle -0
    if quantized == 0:
        return "0"
    
    # Convert to string
    s = str(quantized)
    
    # Remove trailing zeros after decimal point
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    
    return s


def float_to_deterministic_bytes(
    value: Union[float, int, Decimal],
    precision: int = DEFAULT_PRECISION,
) -> bytes:
    """
    Convert a float to deterministic bytes for hashing.
    
    Uses canonical string representation encoded as UTF-8.
    
    Args:
        value: The numeric value
        precision: Decimal precision
        
    Returns:
        UTF-8 encoded canonical representation
    """
    return canonical_float(value, precision).encode('utf-8')
