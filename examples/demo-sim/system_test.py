import requests
import json
import io
import time
from PIL import Image
import piexif
from datetime import datetime

API_URL = "http://localhost:8000/api/v1"

def create_valid_image():
    """Create a 300x300 valid JPEG."""
    img = Image.new('RGB', (300, 300), color='blue')
    buf = io.BytesIO()
    # Add dummy EXIF
    exif_dict = {
        "Exif": {piexif.ExifIFD.DateTimeOriginal: datetime.now().strftime("%Y:%m:%d %H:%M:%S").encode('utf-8')},
        "GPS": {0: (2, 2, 0, 0)}
    }
    exif_bytes = piexif.dump(exif_dict)
    img.save(buf, format='JPEG', exif=exif_bytes)
    return buf.getvalue()

def create_small_image():
    """Create a 50x50 invalid image."""
    img = Image.new('RGB', (50, 50), color='red')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()

def test_system():
    # 1. Valid Submission
    print("Test 1: Submit Valid Observation...", end=" ")
    img_data = create_valid_image()
    payload = {
        "claim_type": "earth.flood.v1",
        "reporter_id": "test_user_sys",
        "geo": {"lat": 10.0, "lon": 10.0},
        "payload": {"water_level_cm": 50}
    }
    
    files = {
        "file": ("evidence.jpg", img_data, "image/jpeg")
    }
    data = {"data": json.dumps(payload)}
    
    r = requests.post(f"{API_URL}/observations/submit", files=files, data=data)
    if r.status_code == 200:
        print(f"[PASS] (TruthKey: {r.json()['truthkey']})")
    else:
        print(f"[FAIL] ({r.status_code}: {r.text})")
        return

    # 2. Duplicate Submission
    print("Test 2: Submit Duplicate Image...", end=" ")
    # Re-use same image
    files = {
        "file": ("evidence.jpg", img_data, "image/jpeg")
    }
    r = requests.post(f"{API_URL}/observations/submit", files=files, data=data)
    if r.status_code == 422 and "DUPLICATE_IMAGE" in r.text:
        print("[PASS] (Caught Duplicate)")
    else:
        print(f"[FAIL] (Expected 422 Duplicate, got {r.status_code}: {r.text})")

    # 3. Invalid Image (Too Small)
    print("Test 3: Submit Small Image...", end=" ")
    small_data = create_small_image()
    # Pad to pass file size check (>1KB)
    small_data = small_data + b'\x00' * 1024
    
    files = {
        "file": ("small.jpg", small_data, "image/jpeg")
    }
    r = requests.post(f"{API_URL}/observations/submit", files=files, data=data)
    if r.status_code == 422 and "IMAGE_TOO_SMALL" in r.text:
        print("[PASS] (Caught Small Image)")
    else:
        print(f"[FAIL] (Expected 422 Small Image, got {r.status_code}: {r.text})")

if __name__ == "__main__":
    time.sleep(2) # Give server time to start
    try:
        test_system()
    except Exception as e:
        print(f"System Test Error: {e}")
