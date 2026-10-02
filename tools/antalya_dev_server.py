"""
Local Kaori for the Antalya contract run (liminal-mobile mobile/scripts/antalya-contract.ts). In-memory stores,
no AI service, and stand-in logins: "Bearer tok-X" is user:X, "Bearer ai-generalist" is the AI validator.
Seeds from KAORI_DEV_SEEDS (comma-separated names, default "S"). Export token: KAORI_EXPORT_TOKEN (default dev-export).
KAORI_DEV_FAKE_PHONE=1 adds a stand-in secure chip at /__fake_phone/* (tools/fake_phone.py) and trusts only its
test root for linking phones, so the app's link and signing code can run end to end without an Android phone.

    KAORI_SCHEMA_PATH=packages/kaori-spec/schemas python tools/antalya_dev_server.py
"""
import os

os.environ.setdefault("KAORI_ANTALYA", "1")
os.environ.setdefault("KAORI_EXPORT_TOKEN", "dev-export")
os.environ.setdefault("KAORI_NAME_KEY", __import__("secrets").token_hex(32))   # names sealed for this run only

import uvicorn  # noqa: E402

from kaori_api import antalya  # noqa: E402
from kaori_api.app import create_app  # noqa: E402
from kaori_api.auth import AuthError  # noqa: E402
from kaori_api.evidence_store import InMemoryEvidenceStore  # noqa: E402
from kaori_flow import FlowCore, InMemorySignalStore  # noqa: E402


def verify(token: str) -> str:
    if token == "ai-generalist":
        return "ai:generalist_v1"
    if token.count(".") == 2 and os.environ.get("KAORI_DEV_TRUST_JWT_SUB") == "1":
        # web previews: trust the unsigned `sub` of a Supabase-shaped token (local dev only)
        import base64, json
        part = token.split(".")[1]
        sub = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("sub")
        if sub:
            return "user:" + sub
    if not token.startswith("tok-"):
        raise AuthError("bad token")
    return "user:" + token[4:]


flow = FlowCore(store=InMemorySignalStore())
for name in filter(None, os.environ.get("KAORI_DEV_SEEDS", "S").split(",")):
    antalya.seed_member(flow, "user:" + name.strip(), callsign="Seed " + name.strip())
generalist = None
if os.environ.get("KAORI_GENERALIST_URL"):
    # a local generalist (tools: uvicorn kaori_api.generalist_app:app); no Cloud Run IAM locally
    from kaori_api.generalist_client import GeneralistClient

    generalist = GeneralistClient(os.environ["KAORI_GENERALIST_URL"], token_provider=lambda audience: "local")
app = create_app(flow=flow, verify_token=verify, generalist_client=generalist,
                 evidence_store=InMemoryEvidenceStore(bucket_name="kaori-observations"),
                 schema_path=os.environ.get("KAORI_SCHEMA_PATH"))

if os.environ.get("KAORI_DEV_FAKE_PHONE") == "1":
    import sys
    from pathlib import Path

    from fastapi import Body

    from kaori_api import attestation, devices

    sys.path.insert(0, str(Path(__file__).parent))
    from fake_phone import FAKE_APP_CERT, FakeChip

    chip = FakeChip()
    devices.TRUST = attestation.TrustData([chip.root.spki], {})
    os.environ["KAORI_ANDROID_CERT_SHA256"] = FAKE_APP_CERT

    @app.post("/__fake_phone/generate")
    def fake_generate(body: dict = Body(...)):
        return chip.generate(body["alias"], body["challenge"].encode())

    @app.post("/__fake_phone/sign")
    def fake_sign(body: dict = Body(...)):
        return {"signature": chip.sign(body["alias"], body["text"])}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8787")), log_level="warning")
