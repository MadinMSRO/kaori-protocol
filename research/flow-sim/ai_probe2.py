import sys, torch
from pathlib import Path
from PIL import Image
sys.argv=[sys.argv[0]]
exec(open(Path(__file__).parent/'ai_check.py').read().split("print(f\"{'photo'")[0])
P = Path(__file__).parent/'photos'
v.model._load(); m, pre, tok = v.model._model, v.model._preprocess, v.model._tokenizer
def probs(img, texts):
    with torch.inference_mode():
        a = m.encode_image(pre(img).unsqueeze(0)); a = a / a.norm(dim=-1, keepdim=True)
        t = m.encode_text(tok(texts)); t = t / t.norm(dim=-1, keepdim=True)
        return (m.logit_scale.exp() * a @ t.T).softmax(dim=-1)[0]
POS = "a photo of the open sky showing how much of it is cloud"
NEG = ["a photo of a person", "a photo of an animal", "a photo of food", "a photo of the inside of a room",
       "a photo of a building", "a photo of a street", "a screenshot of a phone screen", "a photo of a document",
       "a completely black photo", "a blurry photo of the ground"]
variants = {
  'B generic-neg': lambda img: probs(img, [f"evidence of {POS}", "a random unrelated image"])[0].item(),
  'A zero-shot': lambda img: probs(img, [POS] + NEG)[0].item(),
  'A2 3 sky pos': lambda img: probs(img, [POS, "a photo of clouds in the sky", "a photo of a clear blue sky"] + NEG)[:3].sum().item(),
}
imgs = sorted(P.glob('sky/*')) + sorted(P.glob('other/*'))
print(f"{'photo':24}" + ''.join(f"{k:>15}" for k in variants))
for p in imgs:
    img = Image.open(p).convert('RGB')
    print(f"{p.parent.name[:3]+'/'+p.name[:20]:24}" + ''.join(f"{f(img):15.3f}" for f in variants.values()))
