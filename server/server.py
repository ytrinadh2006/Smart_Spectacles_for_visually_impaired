#!/usr/bin/env python3
"""
Smart Specs — Pi Server
========================
Runs on Raspberry Pi Zero 2W.
Receives images via HTTP, runs YOLOv8n TFLite inference,
returns detection results as JSON, and saves images + results to disk.

Usage:
    python3 server.py
    python3 server.py --port 5000 --model model.tflite --labels labels.txt
    python3 server.py --save-dir ~/detections

API Endpoints:
    POST /detect         — Send image, get detections back
    GET  /health         — Check if server is running
    GET  /benchmark      — Run performance benchmark
    GET  /stats          — Get capture statistics
"""

from flask import Flask, request, jsonify, send_from_directory
import argparse
import time
import os
import sys
import json
import threading
from datetime import datetime
from inference import YOLODetector
from tracker import ObjectTracker
from announcer import Announcer
import gen_audio

app = Flask(__name__)
detector = None
save_dir = None
audio_dir = None
tracker = None
announcer = None

# TFLite interpreter is not thread-safe; also guards stats/tracker state
detect_lock = threading.Lock()

# Statistics
stats = {
    'total_frames': 0,
    'total_detections': 0,
    'start_time': None,
    'per_class': {}
}


def save_result(image_bytes, detections, inference_time, original_size):
    """Save image and detection results to disk."""
    if save_dir is None:
        return None

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    frame_num = stats['total_frames']
    
    # Determine subfolder: detections go in 'detected/', empty in 'empty/'
    if detections:
        sub = 'detected'
    else:
        sub = 'empty'
    
    out_dir = os.path.join(save_dir, sub)
    os.makedirs(out_dir, exist_ok=True)
    
    # Save image with rotation applied (same as inference sees)
    img_filename = f'{timestamp}_frame{frame_num:05d}.jpg'
    img_path = os.path.join(out_dir, img_filename)
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    img = img.rotate(180, expand=True)  # match inference rotation
    img.save(img_path, 'JPEG', quality=85)
    
    # Save detection results as JSON alongside the image
    result = {
        'timestamp': timestamp,
        'frame': frame_num,
        'image_file': img_filename,
        'image_size': list(original_size),
        'inference_time_ms': round(inference_time * 1000, 1),
        'detection_count': len(detections),
        'detections': detections
    }
    
    json_filename = f'{timestamp}_frame{frame_num:05d}.json'
    json_path = os.path.join(out_dir, json_filename)
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)
    
    return img_path


@app.route('/health', methods=['GET'])
def health():
    """Check if the server and model are loaded."""
    return jsonify({
        'status': 'ok',
        'model_loaded': detector is not None,
        'labels': detector.labels if detector else [],
        'input_shape': detector.input_shape.tolist() if detector else None,
        'quantized': detector.is_quantized if detector else None,
        'save_dir': save_dir,
        'device': 'Raspberry Pi Zero 2W'
    })


@app.route('/stats', methods=['GET'])
def get_stats():
    """Get capture and detection statistics."""
    uptime = time.time() - stats['start_time'] if stats['start_time'] else 0
    return jsonify({
        'total_frames': stats['total_frames'],
        'total_detections': stats['total_detections'],
        'per_class': stats['per_class'],
        'uptime_seconds': round(uptime),
        'save_dir': save_dir
    })


@app.route('/audio/<path:fname>', methods=['GET'])
def audio(fname):
    """Serve a pre-generated speech clip (raw PCM 16kHz mono u8) to the ESP32."""
    return send_from_directory(audio_dir, fname, mimetype='application/octet-stream')


@app.route('/detect', methods=['POST'])
def detect():
    """
    Receive an image and return detections.
    Also saves the image and results to disk if --save-dir is set.
    """
    if detector is None:
        return jsonify({'error': 'Model not loaded'}), 500

    # Get image data
    if 'image' in request.files:
        image_bytes = request.files['image'].read()
    elif request.data:
        image_bytes = request.data
    else:
        return jsonify({'error': 'No image provided'}), 400

    # Optional: client can report how long capture took
    capture_time_ms = request.form.get('capture_time_ms', type=float, default=None)

    try:
        with detect_lock:
            detections, inference_time, original_size = detector.detect(image_bytes)

            # Build navigation hints using actual image dimensions
            img_w = original_size[0]
            for det in detections:
                box = det['box']
                cx = (box[0] + box[2]) / 2

                if cx < img_w * 0.33:
                    det['position'] = 'left'
                elif cx > img_w * 0.66:
                    det['position'] = 'right'
                else:
                    det['position'] = 'center'

            # Track across frames → adds 'motion' + 'track_id' to each det
            detections = tracker.update(detections)

            # Pick at most one thing to say this frame
            clip, prio = announcer.choose(detections, time.time())

            # Update statistics
            stats['total_frames'] += 1
            stats['total_detections'] += len(detections)
            for det in detections:
                cls = det['class']
                stats['per_class'][cls] = stats['per_class'].get(cls, 0) + 1

            # Save image and results to disk
            saved_path = save_result(image_bytes, detections, inference_time, original_size)

        response = {
            'detections': detections,
            'inference_time_ms': round(inference_time * 1000, 1),
            'count': len(detections),
            'image_size': list(original_size),
            'frame': stats['total_frames'],
            'saved': saved_path is not None,
            'timestamp': time.time(),
            'capture_time_ms': capture_time_ms,
            'speak_url': f'/audio/{clip}.pcm' if clip else '',
            'speak_prio': prio
        }
        # ── Human-readable console output ──────────────────────────────
        frame = stats['total_frames']
        ICON = {'pothole':'🕳️ ', 'vehicle':'🚗', 'obstacle':'🧱',
                'stairs':'🪜', 'safe_path':'🛤️ ', 'person':'🧑',
                'speed_bump':'🔶', 'traffic_light':'🚦',
                'door':'🚪', 'animal':'🐾'}
        if detections:
            print(f"\n┌─ Frame {frame} ─── {time.strftime('%H:%M:%S')} ──────────────────")
            for d in detections:
                icon = ICON.get(d['class'], '•')
                print(f"│  {icon}  {d['class'].upper():15s} {d['confidence']:.0%} confidence  ·  {d['position']}")
            if clip:
                audio_name = clip.replace('_', ' ').replace('.pcm', '')
                print(f"│  🔊  Speaking: \"{audio_name}\"")
            print(f"└─ Inference: {inference_time*1000:.0f}ms ─────────────────────────────")
        else:
            print(f"  Frame {frame} · {time.strftime('%H:%M:%S')} · nothing detected  ({inference_time*1000:.0f}ms)")

        return jsonify(response)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/benchmark', methods=['GET'])
def benchmark():
    """Run a quick benchmark with a dummy image."""
    if detector is None:
        return jsonify({'error': 'Model not loaded'}), 500

    from PIL import Image
    import numpy as np
    import io

    dummy = Image.fromarray(np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8))
    buf = io.BytesIO()
    dummy.save(buf, format='JPEG')
    dummy_bytes = buf.getvalue()

    for _ in range(3):
        detector.detect(dummy_bytes)

    times = []
    runs = 10
    for _ in range(runs):
        _, t, _ = detector.detect(dummy_bytes)
        times.append(t)

    return jsonify({
        'runs': runs,
        'avg_ms': round(sum(times) / len(times) * 1000, 1),
        'min_ms': round(min(times) * 1000, 1),
        'max_ms': round(max(times) * 1000, 1),
        'fps': round(1.0 / (sum(times) / len(times)), 1)
    })


def main():
    global detector, save_dir, audio_dir, tracker, announcer

    parser = argparse.ArgumentParser(description="Smart Specs Detection Server")
    parser.add_argument('--port', type=int, default=5000, help='Port to listen on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--model', type=str, default='/home/smartspecs/pi_scripts/best_int8.tflite')
    parser.add_argument('--labels', type=str, default='/home/smartspecs/pi_scripts/labels.txt')
    parser.add_argument('--threshold', type=float, default=0.4, help='Confidence threshold')
    parser.add_argument('--flip', action='store_true', default=True,
                        help='Flip image vertically (camera is mounted upside-down)')
    parser.add_argument('--save-dir', type=str, default='/home/smartspecs/detections',
                        help='Directory to save images and results')
    parser.add_argument('--audio-dir', type=str,
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audio_cache'),
                        help='Directory holding pre-generated speech clips')
    args = parser.parse_args()

    if not os.path.exists(args.model):
        print(f"❌ Model not found: {args.model}")
        print(f"Transfer your model:")
        print(f"  scp your_model.tflite smartspecs@smartspecs.local:/home/smartspecs/pi_scripts/best_int8.tflite")
        sys.exit(1)

    if not os.path.exists(args.labels):
        print(f"❌ Labels not found: {args.labels}")
        print(f"Create labels.txt with one class name per line")
        sys.exit(1)

    # Setup save directory
    save_dir = args.save_dir
    os.makedirs(os.path.join(save_dir, 'detected'), exist_ok=True)
    os.makedirs(os.path.join(save_dir, 'empty'), exist_ok=True)

    stats['start_time'] = time.time()

    print("=" * 50)
    print("  Smart Specs Detection Server")
    print("=" * 50)
    print(f"Loading model: {args.model}")
    
    detector = YOLODetector(args.model, args.labels, conf_threshold=args.threshold,
                            flip_image=args.flip)
    if args.flip:
        print(f"  Image flip: ✅ enabled (camera mounted upside-down)")

    # Audio: pre-generate any missing speech clips, set up tracker + announcer
    audio_dir = args.audio_dir
    print(f"\nChecking speech clips in: {audio_dir}")
    try:
        made = gen_audio.ensure_cache(detector.labels, audio_dir)
        total = len([f for f in os.listdir(audio_dir) if f.endswith('.pcm')])
        print(f"  {total} clips ready ({made} newly generated)")
    except FileNotFoundError:
        print("  ⚠️ espeak-ng not found — audio announcements disabled until installed")
    tracker = ObjectTracker()
    announcer = Announcer()

    print(f"\nSaving results to: {save_dir}")
    print(f"  detected/ — images with detections + JSON")
    print(f"  empty/    — images with no detections + JSON")
    print(f"\n🚀 Server starting on http://{args.host}:{args.port}")
    print(f"Endpoints:")
    print(f"  POST /detect     — Send image, get detections")
    print(f"  GET  /health     — Check server status")
    print(f"  GET  /stats      — Get capture statistics")
    print(f"  GET  /benchmark  — Run performance test")
    print(f"=" * 50)
    
    # Suppress Flask/Werkzeug "development server" warning banner
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    # threaded=True: the ESP32's /audio GET may overlap the next frame's POST;
    # detect_lock keeps the TFLite interpreter single-threaded.
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
