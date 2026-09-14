#!/bin/bash
# ==========================================
# Smart Specs — Concurrent AP+STA Hotspot
# ==========================================
# Makes the Pi create a SECOND WiFi interface (uap0)
# so it can:
#   - Stay connected to your laptop hotspot (wlan0) → SSH + internet
#   - Broadcast its own AP (uap0) → ESP32 connects here
#
# Result:
#   You SSH via your laptop hotspot as normal
#   ESP32 connects to SmartSpecs-AP
#   No conflict!
# ==========================================

SSID="SmartSpecs-AP"
PASSWORD="smartspecs0102"
AP_IP="192.168.4.1"
AP_INTERFACE="uap0"

echo "========================================="
echo " Smart Specs — Concurrent AP+STA Setup"
echo "========================================="

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo ./setup_hotspot.sh"
    exit 1
fi

# 1. Install packages
echo "[1/5] Installing hostapd and dnsmasq..."
apt install -y hostapd dnsmasq iw

systemctl stop hostapd 2>/dev/null
systemctl stop dnsmasq 2>/dev/null

# 2. Create virtual AP interface (uap0) on top of wlan0
echo "[2/5] Creating virtual AP interface (uap0)..."

# Load driver module with concurrent mode
modprobe brcmfmac 2>/dev/null || true

# Remove existing uap0 if it exists
iw dev uap0 del 2>/dev/null || true

# Create virtual AP interface
iw dev wlan0 interface add uap0 type __ap
if [ $? -ne 0 ]; then
    echo "  ERROR: Could not create uap0 virtual interface"
    echo "  Your Pi firmware may not support concurrent AP+STA"
    echo "  Try: sudo rpi-update && reboot"
    exit 1
fi

ip link set uap0 up
ip addr add ${AP_IP}/24 dev uap0

echo "  ✅ uap0 created with IP $AP_IP"

# 3. Configure hostapd to run on uap0
echo "[3/5] Configuring hostapd..."

cat > /etc/hostapd/hostapd.conf << EOF
# Smart Specs AP — runs on virtual uap0 interface
interface=uap0
driver=nl80211
ssid=$SSID
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$PASSWORD
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
country_code=IN
EOF

# Point hostapd to config
sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' > /etc/default/hostapd

# 4. Configure dnsmasq for DHCP on uap0 only (not wlan0)
echo "[4/5] Configuring DHCP (dnsmasq on uap0)..."

# Back up original dnsmasq config
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null

cat > /etc/dnsmasq.conf << EOF
# Only listen on the AP interface — don't touch wlan0
interface=uap0
bind-interfaces
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
domain=smartspecs
address=/smartspecs.local/$AP_IP
EOF

# 5. Create systemd service to bring up uap0 at boot
echo "[5/5] Creating startup service..."

cat > /etc/systemd/system/smartspecs-ap.service << 'EOF'
[Unit]
Description=Smart Specs — Create uap0 AP interface
After=network.target
Before=hostapd.service dnsmasq.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/sbin/iw dev uap0 del
ExecStart=/sbin/iw dev wlan0 interface add uap0 type __ap
ExecStartPost=/sbin/ip link set uap0 up
ExecStartPost=/sbin/ip addr add 192.168.4.1/24 dev uap0
ExecStop=/sbin/iw dev uap0 del

[Install]
WantedBy=multi-user.target
EOF

# Create detection server service
cat > /etc/systemd/system/smartspecs-server.service << EOF
[Unit]
Description=Smart Specs Detection Server
After=network.target smartspecs-ap.service
Wants=smartspecs-ap.service

[Service]
Type=simple
User=smartspecs
WorkingDirectory=/home/smartspecs/pi_scripts
ExecStart=/home/smartspecs/pi_scripts/venv/bin/python3 /home/smartspecs/pi_scripts/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable all services
systemctl daemon-reload
systemctl enable smartspecs-ap.service
systemctl enable hostapd.service
systemctl enable dnsmasq.service
systemctl enable smartspecs-server.service

# Start them now
systemctl start smartspecs-ap.service
sleep 1
systemctl start hostapd
sleep 1
systemctl start dnsmasq

echo ""
echo "========================================="
echo " ✅ Concurrent AP+STA Setup Complete!"
echo "========================================="
echo ""
echo " wlan0 (STA): stays connected to your laptop hotspot"
echo "              → you keep SSH + internet as normal"
echo ""
echo " uap0  (AP):  broadcasts SmartSpecs-AP"
echo "              → ESP32 connects here"
echo "              → Pi IP on this network: $AP_IP"
echo ""
echo " WiFi for ESP32:"
echo "   SSID:     $SSID"
echo "   Password: $PASSWORD"
echo "   Pi IP:    $AP_IP"
echo ""
echo " Verify it's working:"
echo "   iw dev          # should show both wlan0 and uap0"
echo "   ip addr         # should show 192.168.4.1 on uap0"
echo "   systemctl status hostapd"
echo ""
echo " The detection server will auto-start on next boot."
echo " Start it now:"
echo "   sudo systemctl start smartspecs-server"
echo "   # or manually:"
echo "   cd ~/pi_scripts && source venv/bin/activate && python3 server.py"
echo "========================================="
