"""
Kaori Core — Bouncer Validators

Lightweight, fast validation checks to reject spam/garbage.
"""
from datetime import datetime, timezone
import io
import hashlib
from typing import Any, Tuple, Optional

from PIL import Image
import imagehash
import piexif


def validate_image_file(file_bytes: bytes, min_width: int = 200, min_height: int = 200) -> Tuple[bool, Optional[str]]:
    """
    Check if bytes are a valid image and meet minimum dimensions.
    Returns (Passed, RejectionReason).
    """
    try:
        if len(file_bytes) < 1024:  # < 1KB
            return False, "FILE_TOO_SMALL"
            
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()  # Check for corruption
        
        # Re-open after verify() closes file
        img = Image.open(io.BytesIO(file_bytes))
        width, height = img.size
        
        if width < min_width or height < min_height:
            return False, f"IMAGE_TOO_SMALL_{width}x{height}"
            
        if img.format not in ["JPEG", "PNG", "WEBP"]:
            return False, f"INVALID_FORMAT_{img.format}"
            
        return True, None
    except Exception as e:
        return False, f"INVALID_IMAGE_FILE: {str(e)}"


def validate_exif_metadata(file_bytes: bytes, required_freshness_hours: int = 48) -> Tuple[bool, Optional[str]]:
    """
    Check if image has plausbile EXIF metadata.
    Returns (Passed, RejectionReason).
    """
    try:
        img = Image.open(io.BytesIO(file_bytes))
        if "exif" not in img.info:
            # Not strictly rejecting for missing EXIF in v1, but could flag
            return True, None
            
        exif_dict = piexif.load(img.info["exif"])
        
        # Check GPS
        gps = exif_dict.get("GPS", {})
        if not gps:
            # Missing GPS is suspicious for mobile reports but allowed for now
            return True, None
            
        # Check Timestamp (DateTimeOriginal)
        exif_ifd = exif_dict.get("Exif", {})
        dt_bytes = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
        
        if dt_bytes:
            dt_str = dt_bytes.decode("utf-8")
            # Format: "YYYY:MM:DD HH:MM:SS"
            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
            # Naive to UTC
            dt = dt.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            age = (now - dt).total_seconds() / 3600
            
            if age > required_freshness_hours:
                return False, f"IMAGE_TOO_OLD_{int(age)}h"
                
        return True, None
        
    except Exception:
        # Malformed EXIF
        return True, None


def compute_phash(file_bytes: bytes) -> str:
    """Compute perceptual hash of image."""
    img = Image.open(io.BytesIO(file_bytes))
    return str(imagehash.phash(img))


def check_duplicate(phash: str, existing_hashes: set[str]) -> bool:
    """Check if pHash is a duplicate (exact match for now)."""
    return phash in existing_hashes





def validate_payload_schema(payload: dict[str, Any], schema_fields: list[dict]) -> Tuple[bool, Optional[str]]:
    """
    Validate JSON payload against schema fields.
    Schema format simplified from UI schema.
    """
    # Placeholder for simple structural check
    for field in schema_fields:
        name = field.get("name")
        required = field.get("required", False)
        
        if required and name not in payload:
            return False, f"MISSING_FIELD_{name}"
            
    return True, None
