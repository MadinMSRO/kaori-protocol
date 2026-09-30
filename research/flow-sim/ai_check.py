# Runs Kaori's own AI check (kaori_api.generalist.ClipGeneralistValidator with open_clip ViT-B-32,
# OpenAI weights) on local photos, as sky-cover reports from Antalya. Prints each photo's confidence,
# the vote, and whether it clears the critical lane's 0.82.
#   python ai_check.py photos/   (photos/sky/*.jpg should pass, photos/other/*.jpg should not)
import hashlib, sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from kaori_api.generalist import ClipGeneralistValidator, ValidatorRequest
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing

ROOT = Path(__file__).resolve().parent
import os
SCHEMAS = os.environ.get("KAORI_SCHEMA_PATH", str(Path(__file__).resolve().parents[2] / "packages/kaori-spec/schemas"))
KEY = "earth:sky_cover:h3:883f6e36d3fffff:surface:2026-10-05T09:00Z"
ANTALYA = {"lat": 36.8969, "lon": 30.7133}

files = {}
def loader(ref: EvidenceRef) -> bytes:
    return files[ref.uri]

def obs(path: Path, cover: str) -> Observation:
    data = path.read_bytes()
    uri = f"gs://local/{path.parent.name}/{path.name}"
    files[uri] = data
    return Observation(
        observation_id=uuid4(), claim_type="earth.sky_cover.v1", reported_at=datetime.now(timezone.utc),
        reporter_id="user:local", reporter_context=ReporterContext(standing=Standing.BRONZE, trust_score=0.2, source_type="human"),
        geo=ANTALYA, payload={"cover": cover, "raining": False},
        evidence_refs=[EvidenceRef(uri=uri, sha256=hashlib.sha256(data).hexdigest())],
    )

# Kaori loads open_clip ViT-B-32 with pretrained="openai"; the download hosts are blocked here, so load
# the same OpenAI file (sha256 40d36571…a950af, verified) from disk. Scoring code is Kaori's, unchanged.
import open_clip
from kaori_api import generalist as g
WEIGHTS = os.path.join(os.environ.get("KAORI_CLIP_CACHE", "/opt/clipw"), "ViT-B-32.pt")
def _load(self):
    if self._model is not None:
        return
    self._model = open_clip.load_openai_model(WEIGHTS, device="cpu")
    self._preprocess = open_clip.image_transform(self._model.visual.image_size, is_train=False)
    self._tokenizer = open_clip.get_tokenizer(g.CLIP_V1_MODEL)
    self._model.eval()
g.OpenClipGeneralist._load = _load

v = ClipGeneralistValidator(schema_root=SCHEMAS, evidence_loader=loader)
base = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "photos")
print(f"{'photo':44} {'conf':>6}  vote     critical(>=0.82)")
for group in ("sky", "other"):
    for p in sorted((base / group).glob("*")):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        vote = v.validate(ValidatorRequest(truthkey_id=KEY, claim_type_id="earth.sky_cover.v1", observations=[obs(p, "few")]))
        print(f"{group + '/' + p.name:44} {vote.confidence:6.3f}  {vote.vote:7}  {'yes' if vote.confidence >= 0.82 else 'no'}")
