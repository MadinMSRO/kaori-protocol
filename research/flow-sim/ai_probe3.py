import sys, torch
from pathlib import Path
from PIL import Image
sys.argv=[sys.argv[0]]
exec(open(Path(__file__).parent/'ai_check.py').read().split("print(f\"{'photo'")[0])
P = Path(__file__).parent/'photos'
v.model._load(); m, pre, tok = v.model._model, v.model._preprocess, v.model._tokenizer
def pos_mass(img, pos, neg):
    with torch.inference_mode():
        a = m.encode_image(pre(img).unsqueeze(0)); a = a / a.norm(dim=-1, keepdim=True)
        t = m.encode_text(tok(pos + neg)); t = t / t.norm(dim=-1, keepdim=True)
        return (m.logit_scale.exp() * a @ t.T).softmax(dim=-1)[0][:len(pos)].sum().item()
POS = ["a photo of the open sky", "a photo of clouds in the sky", "a photo of a clear blue sky", "a photo of a dark stormy sky", "a photo of the sky at sunset", "a photo of the sky above rooftops and trees", "a photo of the sky with the horizon at the bottom"]
NEG_ALL = ["a photo of a person", "a photo of an animal", "a photo of food", "a photo of the inside of a room", "a photo of a building", "a photo of a street", "a screenshot of a phone screen", "a photo of a document", "a completely black photo", "a blurry photo of the ground"]
NEG_SAFE = ["a close-up photo of a person", "a photo of an animal", "a photo of food", "a photo of the inside of a room", "a screenshot of a phone screen", "a photo of a document or text", "a completely black photo", "a blurry close-up photo of the ground"]
NEG_V2 = ["a close-up photo of a person", "a photo of an animal", "a photo of food", "a photo of the inside of a room", "a screenshot of an app with text and buttons", "a photo of a document or text", "a completely black photo", "a photo of a floor, pavement or sand up close"]
sets = {'v2': (POS, NEG_V2), '6pos+allneg': (POS, NEG_ALL), '6pos+safeneg': (POS, NEG_SAFE), '6pos+safe+bldg': (POS, NEG_SAFE + ["a photo of the front of a building"])}
imgs = sorted(P.glob('sky/*')) + sorted(P.glob('other/*'))
print(f"{'photo':30}" + ''.join(f"{k:>16}" for k in sets))
for p in imgs:
    img = Image.open(p).convert('RGB')
    print(f"{p.parent.name[:3]+'/'+p.name[:26]:30}" + ''.join(f"{pos_mass(img,*s):16.3f}" for s in sets.values()))
