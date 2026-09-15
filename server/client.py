#!/usr/bin/env python3
"""
Smart Specs — PC Client
========================
Runs on your PC/laptop.
Sends test images to the Pi server and displays results.

Usage:
    python3 client.py --image test.jpg
    python3 client.py --image test.jpg --pi 192.168.1.100
    python3 client.py --dir ./test_images/
    python3 client.py --benchmark
    python3 client.py --health
"""

import requests
import argparse
import os
import sys
import json
import time
from pathlib import Path

DEFAULT_PI = "smartspecs.local"
DEFAULT_PORT = 5000


def get_base_url(host, port):
    return f"http://{host}:{port}"


def check_health(base_url):
    """Check if the Pi server is running."""
    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        data = r.json()
        print("=" * 50)
        print("  Pi Server Status")
        print("=" * 50)
        print(f"  Status:      {data['status']}")
        print(f"  Model:       {'✅ Loaded' if data['model_loaded'] else '❌ Not loaded'}")
        print(f"  Labels:      {data.get('labels', [])}")
        print(f"  Input shape: {data.get('input_shape', 'N/A')}")
        print(f"  Device:      {data.get('device', 'Unknown')}")
        print("=" * 50)
        return True
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to Pi at {base_url}")
        print(f"   Make sure the Pi is on and the server is running")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def send_image(base_url, image_path, capture_time_ms=None):
    """Send an image to the Pi and get detections."""
    if not os.path.exists(image_path):
        print(f"❌ File not found: {image_path}")
        return None

    filename = os.path.basename(image_path)
    filesize = os.path.getsize(image_path) / 1024  # KB

    print(f"\n📸 Sending: {filename} ({filesize:.1f} KB)")

    try:
        t0 = time.time()
        with open(image_path, 'rb') as f:
            fields = {'image': (filename, f, 'image/jpeg')}
            data = {}
            if capture_time_ms is not None:
                data['capture_time_ms'] = str(capture_time_ms)
            r = requests.post(
                f"{base_url}/detect",
                files=fields,
                data=data,
                timeout=30
            )
        total_time = time.time() - t0

        if r.status_code != 200:
            print(f"❌ Server error: {r.json().get('error', 'Unknown')}")
            return None

        data = r.json()
        inference_ms = data['inference_time_ms']
        transfer_ms = total_time * 1000 - inference_ms

        print(f"\n⏱️  Timing Breakdown:")
        if capture_time_ms is not None:
            print(f"   📷 Capture:       {capture_time_ms:.0f}ms")
        print(f"   📡 Transfer+proc: {transfer_ms:.0f}ms")
        print(f"   🧠 Inference:     {inference_ms:.0f}ms")
        print(f"   ─────────────────────────")
        if capture_time_ms is not None:
            full_total = capture_time_ms + total_time * 1000
            print(f"   🏁 Total:         {full_total:.0f}ms  ({1000/full_total:.1f} FPS)")
        else:
            print(f"   🏁 Round-trip:    {total_time*1000:.0f}ms")
        print(f"\n📦 Detections: {data['count']}")

        if data['detections']:
            print(f"\n{'Class':<15} {'Confidence':<12} {'Position':<10} {'Box'}")
            print("-" * 60)
            for det in data['detections']:
                box = det['box']
                print(f"  {det['class']:<13} {det['confidence']*100:>5.1f}%     "
                      f"{det.get('position', 'N/A'):<10}"
                      f"[{box[0]:.0f}, {box[1]:.0f}, {box[2]:.0f}, {box[3]:.0f}]")
        else:
            print("  No objects detected")

        return data

    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to Pi at {base_url}")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def send_directory(base_url, dir_path):
    """Send all images in a directory."""
    extensions = {'.jpg', '.jpeg', '.png', '.bmp'}
    images = sorted([
        os.path.join(dir_path, f) for f in os.listdir(dir_path)
        if Path(f).suffix.lower() in extensions
    ])

    if not images:
        print(f"❌ No images found in {dir_path}")
        return

    print(f"Found {len(images)} images in {dir_path}")
    
    all_results = []
    total_inference = 0
    total_detections = 0

    for img_path in images:
        result = send_image(base_url, img_path)
        if result:
            all_results.append(result)
            total_inference += result['inference_time_ms']
            total_detections += result['count']

    print(f"\n{'='*50}")
    print(f"  Summary")
    print(f"{'='*50}")
    print(f"  Images processed: {len(all_results)}/{len(images)}")
    print(f"  Total detections: {total_detections}")
    if all_results:
        print(f"  Avg inference:    {total_inference/len(all_results):.0f}ms")
    print(f"{'='*50}")


def run_benchmark(base_url):
    """Ask Pi to run its internal benchmark."""
    print("Running benchmark on Pi (10 inference runs)...")
    try:
        r = requests.get(f"{base_url}/benchmark", timeout=120)
        data = r.json()
        print(f"\n{'='*50}")
        print(f"  Benchmark Results")
        print(f"{'='*50}")
        print(f"  Runs:     {data['runs']}")
        print(f"  Average:  {data['avg_ms']}ms")
        print(f"  Min:      {data['min_ms']}ms")
        print(f"  Max:      {data['max_ms']}ms")
        print(f"  FPS:      {data['fps']}")
        print(f"{'='*50}")
    except Exception as e:
        print(f"❌ Benchmark failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Smart Specs PC Client")
    parser.add_argument('--pi', type=str, default=DEFAULT_PI, help='Pi hostname or IP')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='Pi server port')
    parser.add_argument('--image', type=str, help='Path to image file')
    parser.add_argument('--dir', type=str, help='Path to directory of images')
    parser.add_argument('--capture-time', type=float, default=None,
                        help='Camera capture time in ms (for full pipeline timing)')
    parser.add_argument('--health', action='store_true', help='Check Pi server health')
    parser.add_argument('--benchmark', action='store_true', help='Run benchmark on Pi')
    args = parser.parse_args()

    base_url = get_base_url(args.pi, args.port)
    print(f"🔗 Pi server: {base_url}")

    if args.health:
        check_health(base_url)
    elif args.benchmark:
        run_benchmark(base_url)
    elif args.image:
        send_image(base_url, args.image, capture_time_ms=args.capture_time)
    elif args.dir:
        send_directory(base_url, args.dir)
    else:
        # Default: check health
        if check_health(base_url):
            print("\nReady! Try:")
            print(f"  python3 client.py --image photo.jpg --pi {args.pi}")
            print(f"  python3 client.py --dir ./test_images/ --pi {args.pi}")
            print(f"  python3 client.py --benchmark --pi {args.pi}")


if __name__ == "__main__":
    main()
