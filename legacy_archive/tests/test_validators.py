"""
Tests for Kaori Core Validators
"""
import io
import pytest
import torch
from PIL import Image
import piexif
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from core.validators import bouncer, ValidationPipeline, generalist

def create_test_image_bytes(width=200, height=200, format="JPEG", exif_data=None):
    """Helper to create image bytes for testing."""
    img = Image.new('RGB', (width, height), color='red')
    
    # Add EXIF if provided
    exif_bytes = b""
    if exif_data:
        exif_bytes = piexif.dump(exif_data)
        
    buf = io.BytesIO()
    img.save(buf, format=format, exif=exif_bytes)
    return buf.getvalue()

class TestBouncerImageValidation:
    
    def test_valid_image(self):
        img_bytes = create_test_image_bytes(width=300, height=300)
        ok, reason = bouncer.validate_image_file(img_bytes)
        assert ok is True
        assert reason is None
        
    def test_image_too_small(self):
        # Create small image but ensure file size > 1KB so it passes file size check
        img_bytes = create_test_image_bytes(width=10, height=10)
        # Pad with zeroes to pass 1KB check
        img_bytes = img_bytes + b'\x00' * 1024
        ok, reason = bouncer.validate_image_file(img_bytes)
        assert ok is False
        assert "IMAGE_TOO_SMALL" in reason
        
    def test_corrupted_file(self):
        # Large enough but random junk
        img_bytes = b"not an image file" * 100
        ok, reason = bouncer.validate_image_file(img_bytes)
        assert ok is False
        assert "INVALID_IMAGE_FILE" in reason

class TestBouncerExif:
    
    def test_no_exif_allowed(self):
        # v1 allows missing exif
        img_bytes = create_test_image_bytes()
        ok, reason = bouncer.validate_exif_metadata(img_bytes)
        assert ok is True
        
    def test_fresh_exif(self):
        # Create EXIF with recent timestamp AND GPS (required to proceed to timestamp check)
        now_str = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
        exif_dict = {
            "GPS": {0: (2, 2, 0, 0)}, # Minimal dummy GPS
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: now_str.encode("utf-8")
            }
        }
        img_bytes = create_test_image_bytes(exif_data=exif_dict)
        ok, reason = bouncer.validate_exif_metadata(img_bytes)
        assert ok is True
        
    def test_stale_exif(self):
        # Timestamp from 2020 + GPS
        exif_dict = {
            "GPS": {0: (2, 2, 0, 0)}, # Minimal dummy GPS
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: b"2020:01:01 12:00:00"
            }
        }
        img_bytes = create_test_image_bytes(exif_data=exif_dict)
        ok, reason = bouncer.validate_exif_metadata(img_bytes)
        assert ok is False
        assert "IMAGE_TOO_OLD" in reason

class TestBouncerDuplicates:
    
    def test_duplicate_detection(self):
        pipeline = ValidationPipeline()
        img_bytes = create_test_image_bytes()
        
        # First submission OK
        ok, reason = pipeline.run_bouncer(img_bytes, {}, {})
        assert ok is True
        
        # Second submission REJECTED
        ok, reason = pipeline.run_bouncer(img_bytes, {}, {})
        assert ok is False
        assert reason == "DUPLICATE_IMAGE"

class TestGeneralistCLIP:
    
    @patch('core.validators.generalist._get_clip')
    def test_check_safety_safe(self, mock_get_clip):
        # Mock CLIP output: [Safe=0.9, NSFW=0.05, Gore=0.05]
        mock_model = MagicMock()
        mock_processor = MagicMock()
        mock_get_clip.return_value = (mock_model, mock_processor)
        
        # Create mock output tensor
        # shape [1, 3] e.g.
        mock_output = MagicMock()
        # logits_per_image.softmax(dim=1) -> tensor([[0.9, 0.05, 0.05]])
        mock_output.logits_per_image.softmax.return_value = torch.tensor([[0.9, 0.05, 0.05]])
        mock_model.return_value = mock_output
        
        img_bytes = create_test_image_bytes()
        is_safe = generalist.check_content_safety(img_bytes)
        assert is_safe is True

    @patch('core.validators.generalist._get_clip')
    def test_check_safety_unsafe(self, mock_get_clip):
        # Mock CLIP output: [Safe=0.1, NSFW=0.8, Gore=0.1]
        mock_model = MagicMock()
        mock_processor = MagicMock()
        mock_get_clip.return_value = (mock_model, mock_processor)
        
        mock_output = MagicMock()
        mock_output.logits_per_image.softmax.return_value = torch.tensor([[0.1, 0.8, 0.1]])
        mock_model.return_value = mock_output
        
        img_bytes = create_test_image_bytes()
        is_safe = generalist.check_content_safety(img_bytes)
        assert is_safe is False
