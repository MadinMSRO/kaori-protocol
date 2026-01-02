"""
Kaori Core — Validation Pipeline

Orchestrates the validation flow (Bouncer -> Generalist -> Specialist).
"""
from typing import Optional, Tuple
from core.validators import bouncer

class ValidationPipeline:
    """
    Orchestrates validation checks for an observation.
    """
    def __init__(self):
        # In-memory duplicate cache (replace with Redis/DB in prod)
        self.seen_hashes = set()

    def run_bouncer(self, file_bytes: bytes, payload: dict, schema_config: dict) -> Tuple[bool, Optional[str]]:
        """
        Run fast/cheap bouncer checks.
        """
        # 1. Image Validity
        ok, reason = bouncer.validate_image_file(file_bytes)
        if not ok:
            return False, reason
            

        ok, reason = bouncer.validate_exif_metadata(file_bytes)
        if not ok:
            return False, reason
            
        # 4. Duplicate Check
        phash = bouncer.compute_phash(file_bytes)
        if bouncer.check_duplicate(phash, self.seen_hashes):
            return False, "DUPLICATE_IMAGE"
        
        self.seen_hashes.add(phash)
        
        # 5. Payload Check
        # (Assuming schema_config has ui_schema fields)
        fields = schema_config.get("ui_schema", {}).get("fields", [])
        ok, reason = bouncer.validate_payload_schema(payload, fields)
        if not ok:
            return False, reason
            
        return True, None
