# Same model and Kaori's own scoring (two texts: "evidence of {context}" vs "a random image unrelated
# to {context}", softmax), trying different base contexts and matching payloads per photo.
import sys, io, torch, open_clip
from pathlib import Path
from PIL import Image
sys.argv=[sys.argv[0]]
exec(open(Path(__file__).parent/'ai_check.py').read().split("print(f\"{'photo'")[0])  # reuse setup, loader, v
from kaori_api.generalist import ValidatorRequest
P = Path(__file__).parent/'photos'
LABEL = {'skyar-cloudy.jpg': ('overcast', False), 'skyar-rainy.jpg': ('overcast', True), 'skyar-sunny.jpg': ('clear', False), 'skyar-sunset.jpg': ('scattered', False)}
v.model._load()
m, pre, tok = v.model._model, v.model._preprocess, v.model._tokenizer
cfg = v._load_claim_type('earth.sky_cover.v1')
def score(img, ctx):
    with torch.inference_mode():
        a = m.encode_image(pre(img).unsqueeze(0)); a = a / a.norm(dim=-1, keepdim=True)
        t = m.encode_text(tok([f"evidence of {ctx}", f"a random image unrelated to {ctx}"])); t = t / t.norm(dim=-1, keepdim=True)
        return (m.logit_scale.exp() * a @ t.T).softmax(dim=-1)[0, 0].item()
bases = {
  'current': 'a photo of the open sky showing how much of it is cloud',
  'short': 'the sky',
  'sky photo': 'a photo of the sky',
  'clouds': 'a photo of the sky and clouds',
}
imgs = sorted(P.glob('sky/*')) + sorted(P.glob('other/*'))
print(f"{'photo':24}" + ''.join(f"{k:>12}" for k in bases) + f"{'bare':>10}")
for p in imgs:
    img = Image.open(p).convert('RGB')
    cover, rain = LABEL.get(p.name, ('few', False))
    o = obs(p, cover); o.payload['raining'] = rain
    req = ValidatorRequest(truthkey_id=KEY, claim_type_id='earth.sky_cover.v1', observations=[o])
    row = []
    for k, b in bases.items():
        row.append(score(img, v._package_context(b, req, cfg)))
    bare = score(img, 'a photo of the sky')
    print(f"{p.parent.name[:3]+'/'+p.name[:20]:24}" + ''.join(f"{x:12.3f}" for x in row) + f"{bare:10.3f}")
print('context example:', v._package_context(bases['current'], req, cfg)[:300])
