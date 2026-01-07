from core.validators import generalist
import io
from PIL import Image

def test_generalist():
    print("Initializing Generalist (Lazy Loading CLIP)...")
    
    # Create a simple image
    img = Image.new('RGB', (200, 200), color='green')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    data = buf.getvalue()
    
    # Check Safety
    print("Running check_content_safety...")
    is_safe = generalist.check_content_safety(data)
    print(f"Safety Result: {is_safe}")
    
    # Check Confidence
    print("Running compute_confidence...")
    conf = generalist.compute_confidence(data, "earth.flood.v1")
    print(f"Confidence Score: {conf:.4f}")

    if conf > 0.5: # CLIP should be somewhat confident it's an image. 
        # Actually a green square might have low confidence for "a flood", 
        # but the point is it returns a float, not crashes.
        print("✅ Generalist Executed Successfully")
    else:
        print("⚠️ Generalist Executed (Low Confidence)")

if __name__ == "__main__":
    test_generalist()
