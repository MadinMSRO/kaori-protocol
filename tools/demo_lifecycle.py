import requests
import json
import io
import time
import sys
from PIL import Image
import piexif
from datetime import datetime

API_URL = "http://localhost:8001/api/v1"

from PIL import Image, ImageDraw
import random

def create_valid_image():
    """Create a 300x300 valid JPEG with random structure."""
    img = Image.new('RGB', (300, 300), color='blue')
    draw = ImageDraw.Draw(img)
    # Draw random rectangle to change pHash
    x = random.randint(0, 200)
    y = random.randint(0, 200)
    draw.rectangle([x, y, x+50, y+50], fill='red')
    
    buf = io.BytesIO()
    # Add dummy EXIF
    exif_dict = {
        "Exif": {piexif.ExifIFD.DateTimeOriginal: datetime.now().strftime("%Y:%m:%d %H:%M:%S").encode('utf-8')},
        "GPS": {0: (2, 2, 0, 0)}
    }
    exif_bytes = piexif.dump(exif_dict)
    img.save(buf, format='JPEG', exif=exif_bytes)
    return buf.getvalue()

def demo_lifecycle():
    print("=== Kaori Protocol: Full Lifecycle Demo ===\n")

    # 1. REPORTER: Submit Observation
    print("1. [Reporter] Submitting Observation...")
    img_data = create_valid_image()
    payload = {
        "claim_type": "earth.flood.v1",
        "reporter_id": "reporter_alice",
        "geo": {"lat": 10.0, "lon": 10.0},
        "payload": {"water_level_cm": 50}
    }
    files = {"file": ("flood.jpg", img_data, "image/jpeg")}
    print("1. [Reporter] Submitting Observation...")
    try:
        # Step 1: Submit (Async Ingest)
        response = requests.post(f"{API_URL}/observations/submit", data={"payload": json.dumps(payload)}, files=files)
        
        if response.status_code != 202:
            print(f"[ERROR] Submission Failed: {response.text}")
            sys.exit(1)
            
        data = response.json()
        ingest_id = data.get("ingest_id")
        print(f"[OK] Submission Accepted! Ingest ID: {ingest_id}")
        
        # Step 2: Poll for Processing
        print("   Polling for processing status...")
        truthkey_str = None
        for i in range(10):
            import time
            time.sleep(1)
            status_resp = requests.get(f"{API_URL}/observations/submit/{ingest_id}")
            if status_resp.status_code == 200:
                s_data = status_resp.json()
                status = s_data.get("status")
                print(f"   Status: {status}")
                if status == "PROCESSED":
                    truthkey_str = s_data.get("result_truthkey")
                    print(f"[OK] Processing Complete! TruthKey: {truthkey_str}")
                    break
                elif status == "INVALID":
                     print(f"[ERROR] Processing Invalid: {s_data.get('error')}")
                     sys.exit(1)
                     
        if not truthkey_str:
             print("[ERROR] Timed out waiting for processing.")
             sys.exit(1)

    except Exception as e:
        print(f"[ERROR] Request Exception: {e}")
        sys.exit(1)

    # 2. Oracle Check
    print("\n2. [Oracle] Checking Truth State...")
    try:
        # Parse TruthKey to get ID? No, we have the string.
        pass
    except Exception:
        pass

    response = requests.get(f"{API_URL}/truth/state/{truthkey_str}")
    state = response.json() # Changed r to response
    print(f"   Confidence: {state['confidence']}")
    print(f"   Status:     {state['status']}\n")

    # 3. VALIDATORS: Submit Votes to Ratify
    print("3. [Validators] Crowd Consensus Begins...")
    # We need enough votes to reach threshold.
    # Default threshold might be high (15), Bronze weight is likely 1 or 5.
    # Let's cast 4 votes.
    validators = ["val_bob", "val_charlie", "val_dave", "val_eve"]
    
    for val in validators:
        vote_payload = {
            "truthkey": truthkey_str,
            "voter_id": val,
            "vote_type": "RATIFY",
            "comment": "Looks like a flood."
        }
        r = requests.post(f"{API_URL}/votes", json=vote_payload)
        if r.status_code == 200:
            v_resp = r.json()
            is_final = v_resp["consensus_finalized"]
            score = v_resp["consensus_score"]
            print(f"   [VOTE] Cast by {val} -> Score: {score} (Finalized: {is_final})")
            if is_final:
                print("   [!!!] CONSENSUS REACHED!")
                break
        else:
            print(f"   [X] Vote Failed: {r.text}")
    
    print("")

    # 4. ORACLE: Verify Final State
    print("4. [Oracle] Verifying Final Truth State...")
    r = requests.get(f"{API_URL}/truth/state/{truthkey_str}")
    final_state = r.json()
    
    print(f"   Status:     {final_state['status']}")
    print(f"   Confidence: {final_state['confidence']}")
    print(f"   Verified By: {final_state.get('verification_basis', 'N/A')}")
    
    if final_state['status'] == "VERIFIED_TRUE":
        print("\n[SUCCESS] Full End-to-End Flow Completed!")
    else:
        print("\n[WARNING] Did not reach VERIFIED_TRUE state (Need more votes?)")

if __name__ == "__main__":
    time.sleep(2)
    demo_lifecycle()
