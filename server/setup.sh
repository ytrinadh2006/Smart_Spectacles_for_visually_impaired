#!/bin/bash
# ==========================================
# Smart Specs — First Boot Setup Script
# Run this after first SSH into the Pi
# ==========================================

echo "========================================="
echo " Smart Specs — Pi Zero 2W Setup"
echo "========================================="

# 1. Update
echo "[1/5] Updating system packages..."
sudo apt update && sudo apt upgrade -y

# 2. Install dependencies
echo "[2/5] Installing system dependencies..."
sudo apt install -y \
    python3-pip python3-venv python3-numpy python3-pil \
    libjpeg-dev libopenjp2-7 libopenblas-dev \
    espeak-ng git

# 3. Setup swap (prevents OOM on Pi Zero 2W with 512MB RAM)
echo "[3/5] Setting up swap space..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l 1G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "  ✅ 1GB swap created"
else
    sudo swapon /swapfile 2>/dev/null || true
    echo "  ✅ Swap already configured"
fi
free -h | head -3

PYTHON_CMD="python3"
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  System Python: $PYTHON_VER (using ai-edge-litert — no pyenv needed)"

# 4. Setup Python venv
echo "[4/5] Setting up Python environment..."
cd ~/pi_scripts

# Remove old venv if exists (in case of re-run)
rm -rf venv 2>/dev/null

$PYTHON_CMD -m venv --system-site-packages venv
source venv/bin/activate

pip install --upgrade pip

# Install Flask and Requests (these always work)
pip install flask requests

# Try installing TFLite runtime (multiple fallbacks)
echo "  Attempting TFLite install..."
pip install ai-edge-litert 2>/dev/null && echo "  ✅ ai-edge-litert installed" || {
    pip install tflite-runtime 2>/dev/null && echo "  ✅ tflite-runtime installed" || {
        pip install --extra-index-url https://www.piwheels.org/simple/ tflite-runtime 2>/dev/null && \
            echo "  ✅ tflite-runtime installed (piwheels)" || {
            echo "  ⚠️  TFLite could not be installed automatically"
            echo "  You may need to build from source or use a different Python version"
        }
    }
}

# 5. Test
echo "[5/5] Testing installation..."
echo -n "  Python: " && python3 --version
echo -n "  NumPy: " && python3 -c "import numpy; print(numpy.__version__)"
echo -n "  Pillow: " && python3 -c "from PIL import Image; print('OK')"
echo -n "  Flask: " && python3 -c "import flask; print(flask.__version__)"
echo -n "  TFLite: " && python3 -c "
try:
    from ai_edge_litert import interpreter; print('ai-edge-litert OK')
except:
    try:
        import tflite_runtime; print('tflite_runtime OK')
    except:
        try:
            import tensorflow as tf; print('tf.lite OK')
        except:
            print('NOT INSTALLED — need manual setup')
"
espeak-ng "Smart specs ready" 2>/dev/null && echo "  espeak: OK" || echo "  espeak: not working (no audio device?)"

echo ""
echo "========================================="
echo " ✅ Setup complete!"
echo ""
echo " Next steps:"
echo "   1. Start the detection server:"
echo "      cd ~/pi_scripts"
echo "      source venv/bin/activate"
echo "      python3 server.py"
echo ""
echo "   2. From your PC, send test images:"
echo "      python3 client.py --image photo.jpg --pi smartspecs.local"
echo "========================================="
