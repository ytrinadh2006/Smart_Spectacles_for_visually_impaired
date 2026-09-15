#!/usr/bin/env python3
"""
Smart Specs — Local Model Test
Run on your PC to test the TFLite model directly (no Pi needed).
"""
import numpy as np
from PIL import Image
import io
import time
import os
import sys
import glob
import json

def load_model(model_path, labels_path):
    """Load TFLite model with multiple backend fallbacks."""
    interpreter = None
    backend = None
    
    try:
        from ai_edge_litert import interpreter as ai_interp
        interpreter = ai_interp.Interpreter(model_path=model_path, num_threads=4)
        backend = "ai-edge-litert"
    except ImportError:
        pass
    
    if interpreter is None:
        try:
            import tflite_runtime.interpreter as tflite
            interpreter = tflite.Interpreter(model_path=model_path, num_threads=4)
            backend = "tflite-runtime"
        except ImportError:
            pass
    
    if interpreter is None:
        try:
            import tensorflow as tf
            interpreter = tf.lite.Interpreter(model_path=model_path, num_threads=4)
            backend = "tensorflow"
        except ImportError:
            pass
    
    # Last resort: try onnxruntime with tflite
    if interpreter is None:
        print("❌ No TFLite backend found!")
        print("   Install one of: ai-edge-litert, tflite-runtime, tensorflow")
        print("   Or: sudo pacman -S python-tensorflow  (Arch)")
        sys.exit(1)
    
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    
    with open(labels_path, 'r') as f:
        labels = [line.strip() for line in f.readlines() if line.strip()]
    
    print(f"[Model] Backend: {backend}")
    print(f"[Model] Input shape: {input_details[0]['shape']}")
    print(f"[Model] Input dtype: {input_details[0]['dtype']}")
    print(f"[Model] Output shape: {output_details[0]['shape']}")
    print(f"[Model] Output dtype: {output_details[0]['dtype']}")
    print(f"[Model] Labels ({len(labels)}): {labels}")
    
    return interpreter, input_details, output_details, labels, backend


def run_detection(interpreter, input_details, output_details, labels, image_path, conf_threshold=0.25):
    """Run detection on a single image and return results."""
    input_shape = input_details[0]['shape']
    input_dtype = input_details[0]['dtype']
    input_h, input_w = input_shape[1], input_shape[2]
    is_quantized = input_dtype == np.uint8 or input_dtype == np.int8
    
    # Load and preprocess
    img = Image.open(image_path).convert('RGB')
    original_size = img.size  # (w, h)
    img_resized = img.resize((input_w, input_h))
    
    if is_quantized:
        img_array = np.array(img_resized, dtype=np.uint8)
    else:
        img_array = np.array(img_resized, dtype=np.float32) / 255.0
    
    img_array = np.expand_dims(img_array, axis=0)
    
    # Run inference
    interpreter.set_tensor(input_details[0]['index'], img_array)
    t0 = time.time()
    interpreter.invoke()
    inference_time = time.time() - t0
    
    output = interpreter.get_tensor(output_details[0]['index'])[0]
    
    # Dequantize if needed
    out_det = output_details[0]
    if out_det['dtype'] == np.uint8 or out_det['dtype'] == np.int8:
        quant = out_det.get('quantization_parameters', {})
        scales = quant.get('scales', [])
        zeros = quant.get('zero_points', [])
        if len(scales) > 0:
            output = (output.astype(np.float32) - zeros[0]) * scales[0]
    
    # Transpose if YOLOv8 format [9, 2100] -> [2100, 9]
    if output.shape[0] == len(labels) + 4:
        output = output.T
    
    num_classes = len(labels)
    boxes_raw = output[:, :4]
    scores_raw = output[:, 4:4+num_classes]
    
    class_ids = np.argmax(scores_raw, axis=1)
    confidences = np.max(scores_raw, axis=1)
    
    # Raw stats for diagnostics
    raw_stats = {
        'cx_range': [float(boxes_raw[:, 0].min()), float(boxes_raw[:, 0].max())],
        'cy_range': [float(boxes_raw[:, 1].min()), float(boxes_raw[:, 1].max())],
        'w_range': [float(boxes_raw[:, 2].min()), float(boxes_raw[:, 2].max())],
        'h_range': [float(boxes_raw[:, 3].min()), float(boxes_raw[:, 3].max())],
        'per_class_max': {labels[i]: float(scores_raw[:, i].max()) for i in range(num_classes)},
        'per_class_above_thresh': {labels[i]: int(np.sum(scores_raw[:, i] > conf_threshold)) for i in range(num_classes)},
    }
    
    # Filter by confidence
    mask = confidences > conf_threshold
    boxes_raw = boxes_raw[mask]
    confidences = confidences[mask]
    class_ids = class_ids[mask]
    
    if len(boxes_raw) == 0:
        return [], inference_time, original_size, raw_stats
    
    # Auto-detect coordinate format
    max_coord = np.max(boxes_raw[:, :2])
    if max_coord > 1.0:
        scale_x = original_size[0] / input_w
        scale_y = original_size[1] / input_h
    else:
        scale_x = original_size[0]
        scale_y = original_size[1]
    
    cx = boxes_raw[:, 0] * scale_x
    cy = boxes_raw[:, 1] * scale_y
    w = boxes_raw[:, 2] * scale_x
    h = boxes_raw[:, 3] * scale_y
    
    x1 = np.clip(cx - w / 2, 0, original_size[0])
    y1 = np.clip(cy - h / 2, 0, original_size[1])
    x2 = np.clip(cx + w / 2, 0, original_size[0])
    y2 = np.clip(cy + h / 2, 0, original_size[1])
    
    boxes = np.stack([x1, y1, x2, y2], axis=1)
    
    # NMS
    areas = (x2 - x1) * (y2 - y1)
    order = confidences.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w_nms = np.maximum(0.0, xx2 - xx1)
        h_nms = np.maximum(0.0, yy2 - yy1)
        inter = w_nms * h_nms
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(iou <= 0.45)[0]
        order = order[inds + 1]
    
    detections = []
    for i in keep:
        detections.append({
            'class': labels[class_ids[i]] if class_ids[i] < len(labels) else f'class_{class_ids[i]}',
            'confidence': float(confidences[i]),
            'box': [float(boxes[i][0]), float(boxes[i][1]), float(boxes[i][2]), float(boxes[i][3])]
        })
    
    return detections, inference_time, original_size, raw_stats


def main():
    model_path = '/home/regent/backup/PR/smart_specs_model/best_int8.tflite'
    labels_path = '/home/regent/backup/PR/smart_specs_model/labels.txt'
    
    # Find test images
    test_dir = '/home/regent/backup/PR/test_images'
    threshold = 0.25  # Use lower threshold for diagnostics
    
    if len(sys.argv) > 1:
        if os.path.isdir(sys.argv[1]):
            test_dir = sys.argv[1]
        elif os.path.isfile(sys.argv[1]):
            # Single image mode
            test_dir = None
            single_image = sys.argv[1]
    
    if len(sys.argv) > 2:
        threshold = float(sys.argv[2])
    
    print("=" * 60)
    print("  Smart Specs — Local Model Test")
    print("=" * 60)
    
    interpreter, input_details, output_details, labels, backend = load_model(model_path, labels_path)
    
    # Collect images
    if test_dir and os.path.isdir(test_dir):
        extensions = ('*.jpg', '*.jpeg', '*.png', '*.bmp', '*.webp')
        images = []
        for ext in extensions:
            images.extend(glob.glob(os.path.join(test_dir, ext)))
            images.extend(glob.glob(os.path.join(test_dir, '**', ext), recursive=True))
        images = sorted(set(images))
    elif test_dir is None:
        images = [single_image]
    else:
        print(f"\n❌ No test images found in {test_dir}")
        print(f"   Put some images there or pass an image path as argument")
        sys.exit(1)
    
    if not images:
        print(f"\n❌ No images found in {test_dir}")
        sys.exit(1)
    
    print(f"\nTesting {len(images)} images (threshold: {threshold*100:.0f}%)")
    print("-" * 60)
    
    # Results summary
    all_results = []
    total_detections = 0
    class_counts = {l: 0 for l in labels}
    class_max_conf = {l: 0.0 for l in labels}
    
    for img_path in images:
        filename = os.path.basename(img_path)
        detections, inf_time, orig_size, raw_stats = run_detection(
            interpreter, input_details, output_details, labels, img_path, threshold
        )
        
        print(f"\n📸 {filename} ({orig_size[0]}x{orig_size[1]}) — {inf_time*1000:.0f}ms")
        
        # Show per-class max confidence for this image
        print(f"   Raw max scores: ", end="")
        for label, score in raw_stats['per_class_max'].items():
            marker = "✅" if score > threshold else "  "
            print(f"{label}={score*100:.1f}%{marker} ", end="")
        print()
        
        if detections:
            for d in detections:
                b = d['box']
                print(f"   → {d['class']:>12} {d['confidence']*100:5.1f}%  [{b[0]:.0f},{b[1]:.0f},{b[2]:.0f},{b[3]:.0f}]")
                class_counts[d['class']] = class_counts.get(d['class'], 0) + 1
                if d['confidence'] > class_max_conf.get(d['class'], 0):
                    class_max_conf[d['class']] = d['confidence']
            total_detections += len(detections)
        else:
            print(f"   → No detections")
        
        all_results.append({
            'file': filename,
            'size': list(orig_size),
            'inference_ms': round(inf_time * 1000, 1),
            'detections': detections,
            'raw_stats': raw_stats
        })
    
    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Images tested:    {len(images)}")
    print(f"  Total detections: {total_detections}")
    print(f"  Threshold:        {threshold*100:.0f}%")
    print(f"\n  Per-class results:")
    for label in labels:
        count = class_counts.get(label, 0)
        max_c = class_max_conf.get(label, 0)
        print(f"    {label:>12}: {count:3d} detections, best confidence: {max_c*100:.1f}%")
    
    if total_detections == 0:
        print(f"\n  ⚠️  NO DETECTIONS AT ALL!")
        print(f"  This likely means the MODEL needs retraining, not a script issue.")
        print(f"  The model might be overfitted to training data or the classes")
        print(f"  don't match real-world images well enough.")
    elif total_detections < len(images) * 0.3:
        print(f"\n  ⚠️  Very few detections — model may need more training data")
    else:
        print(f"\n  ✅ Model appears to be working!")
    
    # Save detailed results
    results_path = '/home/regent/backup/PR/test_results.json'
    with open(results_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Detailed results saved to: {results_path}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
