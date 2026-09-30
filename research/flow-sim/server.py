# Local Kaori sidecar for contract tests: in-memory stores, no AI generalist,
# and a stand-in for the Supabase login check ("Bearer tok-A" -> user:A).
import uvicorn
from kaori_api.app import create_app
from kaori_api.auth import AuthError

def verify(token: str) -> str:
    if token == "ai-generalist":
        return "ai:generalist_v1"  # stands in for the AI validator's vote
    if not token.startswith("tok-"):
        raise AuthError("bad token")
    return "user:" + token[4:]

import os
app = create_app(verify_token=verify, generalist_client=None, schema_path=os.environ.get("SCHEMAS"))
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="warning")
