"""
Local Kaori for the Antalya contract run (liminal-mobile mobile/scripts/antalya-contract.ts). In-memory stores,
no AI service, and stand-in logins: "Bearer tok-X" is user:X, "Bearer ai-generalist" is the AI validator.
Seeds from KAORI_DEV_SEEDS (comma-separated names, default "S"). Export token: KAORI_EXPORT_TOKEN (default dev-export).

    KAORI_SCHEMA_PATH=packages/kaori-spec/schemas python tools/antalya_dev_server.py
"""
import os

os.environ.setdefault("KAORI_ANTALYA", "1")
os.environ.setdefault("KAORI_EXPORT_TOKEN", "dev-export")

import uvicorn  # noqa: E402

from kaori_api import antalya  # noqa: E402
from kaori_api.app import create_app  # noqa: E402
from kaori_api.auth import AuthError  # noqa: E402
from kaori_api.evidence_store import InMemoryEvidenceStore  # noqa: E402
from kaori_flow import FlowCore, InMemorySignalStore  # noqa: E402


def verify(token: str) -> str:
    if token == "ai-generalist":
        return "ai:generalist_v1"
    if not token.startswith("tok-"):
        raise AuthError("bad token")
    return "user:" + token[4:]


flow = FlowCore(store=InMemorySignalStore())
for name in filter(None, os.environ.get("KAORI_DEV_SEEDS", "S").split(",")):
    antalya.seed_member(flow, "user:" + name.strip(), callsign="Seed " + name.strip())
app = create_app(flow=flow, verify_token=verify, generalist_client=None,
                 evidence_store=InMemoryEvidenceStore(bucket_name="kaori-observations"),
                 schema_path=os.environ.get("KAORI_SCHEMA_PATH"))

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8787")), log_level="warning")
