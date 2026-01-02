import requests
import json
import sys

API_URL = "http://localhost:8001/api/v1"
TRUTH_KEY = "earth:flood:h3:8858e06829fffff:surface:2026-01-02T17:00:00Z"

def inspect_state():
    print(f"--- Inspecting Truth State for {TRUTH_KEY} ---")
    try:
        response = requests.get(f"{API_URL}/truth/state/{TRUTH_KEY}")
        if response.status_code == 200:
            state = response.json()
            print(json.dumps(state, indent=2))
        else:
            print(f"[ERROR] API returned {response.status_code}: {response.text}")
            print("Is the server running on port 8001?")
    except Exception as e:
        print(f"[ERROR] Could not connect to API: {e}")
        print("Please ensure the uvicorn server is running.")

if __name__ == "__main__":
    inspect_state()
