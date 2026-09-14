#!/usr/bin/env python3
"""
Quick diagnostic: test the model directly and print raw output.
Run on the Pi: python3 test_model.py /path/to/image.jpg
"""
import sys
import numpy as np
from PIL import Image
from inference import YOLODetector

if len(sys.argv) < 2:
    print("Usage: python3 test_model.py <image_path> [threshold]")
    print("Example: python3 test_model.py test.jpg 0.3")
    sys.exit(1)

image_path = sys.argv[1]
threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25  # lower threshold for diagnostics

print(f"\n{'='*60}")
print(f"  Smart Specs Model Diagnostic")
print(f"{'='*60}")

# Load model
detector = YOLODetector(
    '/home/smartspecs/pi_scripts/best_int8.tflite',
    '/home/smartspecs/pi_scripts/labels.txt',
    conf_threshold=threshold
)

# Load and preprocess image
img = Image.open(image_path).convert('RGB')
print(f"\n[Image] Path: {image_path}")
print(f"[Image] Original size: {img.size}")

img_array, original_size = detector.preprocess(img)
print(f"[Image] After preprocess: shape={img_array.shape}, dtype={img_array.dtype}")
print(f"[Image] Value range: [{img_array.min():.3f}, {img_array.max():.3f}]")

# Run inference
output = detector.run_inference(img_array)
raw = output[0]
print(f"\n[Output] Raw shape: {raw.shape}")
print(f"[Output] Raw dtype: {raw.dtype}")
print(f"[Output] Raw value range: [{raw.min():.4f}, {raw.max():.4f}]")

# Transpose if needed (YOLOv8 format)
if raw.shape[0] == len(detector.labels) + 4:
    raw = raw.T
    print(f"[Output] After transpose: {raw.shape}")

# Analyze raw boxes and scores
boxes = raw[:, :4]
scores = raw[:, 4:]

print(f"\n[Boxes] cx range: [{boxes[:,0].min():.2f}, {boxes[:,0].max():.2f}]")
print(f"[Boxes] cy range: [{boxes[:,1].min():.2f}, {boxes[:,1].max():.2f}]")
print(f"[Boxes] w  range: [{boxes[:,2].min():.2f}, {boxes[:,2].max():.2f}]")
print(f"[Boxes] h  range: [{boxes[:,3].min():.2f}, {boxes[:,3].max():.2f}]")

if boxes[:,0].max() > 1.0:
    print(f"[Boxes] ➡️  Coordinates are in PIXEL space (0 to {int(boxes[:,0].max())})")
else:
    print(f"[Boxes] ➡️  Coordinates are NORMALIZED (0 to 1)")

print(f"\n[Scores] Per-class max confidence:")
for i, label in enumerate(detector.labels):
    max_score = scores[:, i].max()
    count_above = np.sum(scores[:, i] > threshold)
    print(f"  {label:>12}: {max_score*100:.1f}% (best), {count_above} detections above {threshold*100:.0f}%")

# Run full detection pipeline
print(f"\n{'='*60}")
print(f"  Full Detection Results (threshold={threshold*100:.0f}%)")
print(f"{'='*60}")

detections, inference_time, orig_size = detector.detect(image_path)

print(f"  Inference time: {inference_time*1000:.0f}ms")
print(f"  Detections: {len(detections)}")

if detections:
    print(f"\n  {'Class':>12}  {'Conf':>6}  {'Box (x1, y1, x2, y2)'}")
    print(f"  {'-'*50}")
    for d in detections:
        b = d['box']
        print(f"  {d['class']:>12}  {d['confidence']*100:5.1f}%  [{b[0]:.0f}, {b[1]:.0f}, {b[2]:.0f}, {b[3]:.0f}]")
else:
    print("\n  No detections. Try:")
    print("    - Lowering threshold: python3 test_model.py image.jpg 0.1")
    print("    - Using an image with pothole/vehicle/obstacle/stairs")
print(f"\n{'='*60}")
