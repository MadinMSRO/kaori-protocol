"""
Kaori Core — Generalist Validators

Implemented with OpenAI CLIP (via HuggingFace Transformers).
Handles Confidence Scoring and Content Safety.
"""
import io
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

# Global model cache (lazy loaded)
_CLIP_MODEL = None
_CLIP_PROCESSOR = None

def _get_clip():
    """Lazy load CLIP model."""
    global _CLIP_MODEL, _CLIP_PROCESSOR
    if _CLIP_MODEL is None:
        model_id = "openai/clip-vit-base-patch32"
        _CLIP_MODEL = CLIPModel.from_pretrained(model_id)
        _CLIP_PROCESSOR = CLIPProcessor.from_pretrained(model_id)
    return _CLIP_MODEL, _CLIP_PROCESSOR

def compute_confidence(file_bytes: bytes, claim_type: str = "general") -> float:
    """
    Compute confidence that image matches the claim type context.
    
    Uses CLIP to compare image against:
    - Positive prompt: "a photo of {context}"
    - Negative prompt: "a photo of something else"
    """
    try:
        model, processor = _get_clip()
        image = Image.open(io.BytesIO(file_bytes))
        
        # Define context based on claim type (simplified mapping)
        context_map = {
            "earth.flood.v1": "a flood",
            "ocean.coral_bleaching.v1": "coral reef bleaching",
            "space.orbital_debris.v1": "space debris",
            "general": "an environmental event"
        }
        context = context_map.get(claim_type, "an environmental event")
        
        prompts = [f"a photo of {context}", "a photo of something else"]
        
        inputs = processor(text=prompts, images=image, return_tensors="pt", padding=True)
        
        with torch.no_grad():
            outputs = model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=1)
            
        # Return probability of positive prompt
        return float(probs[0][0])
    except Exception as e:
        print(f"CLIP Error: {e}")
        return 0.5  # Fail open (neutral)

def check_content_safety(file_bytes: bytes) -> bool:
    """
    Check for NSFW/Gore using CLIP zero-shot classification.
    Returns True if Safe, False if Unsafe.
    """
    try:
        model, processor = _get_clip()
        image = Image.open(io.BytesIO(file_bytes))
        
        prompts = [
            "a safe photo", 
            "a photo containing nudity or sexual content",
            "a photo containing gore or graphic violence"
        ]
        
        inputs = processor(text=prompts, images=image, return_tensors="pt", padding=True)
        
        with torch.no_grad():
            outputs = model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=1)
            
        # Get probabilities
        p_safe = float(probs[0][0])
        p_nsfw = float(probs[0][1])
        p_gore = float(probs[0][2])
        
        # Thresholds (tunable)
        if p_nsfw > 0.5 or p_gore > 0.5:
            return False
            
        return True
    except Exception as e:
        print(f"Safety Check Error: {e}")
        return True  # Fail open
