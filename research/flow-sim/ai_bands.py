import sys, torch
from pathlib import Path
from PIL import Image
sys.argv=[sys.argv[0]]
exec(open(Path(__file__).parent/'ai_check.py').read().split("print(f\"{'photo'")[0])
v.model._load(); m, pre, tok = v.model._model, v.model._preprocess, v.model._tokenizer
BANDS = {"clear": "a photo of a clear blue sky with no clouds", "few": "a photo of a blue sky with a few small clouds",
         "scattered": "a photo of a sky half covered with clouds", "broken": "a photo of a mostly cloudy sky with small patches of blue",
         "overcast": "a photo of a completely overcast grey sky"}
for p in sorted((Path(__file__).parent/'photos'/'sky').glob('*')):
    with torch.inference_mode():
        a = m.encode_image(pre(Image.open(p).convert('RGB')).unsqueeze(0)); a = a / a.norm(dim=-1, keepdim=True)
        t = m.encode_text(tok(list(BANDS.values()))); t = t / t.norm(dim=-1, keepdim=True)
        pr = (m.logit_scale.exp() * a @ t.T).softmax(dim=-1)[0].tolist()
    k = list(BANDS); best = max(range(5), key=lambda i: pr[i])
    print(f"{p.name:34} AI says {k[best]:9} ({pr[best]:.2f})   clear {pr[0]:.2f} · overcast {pr[4]:.2f}")
