#!/usr/bin/env bash
# Start ALL 50 Torguard SOCKS5-to-HTTP proxy bridges.
# Ports: 9080-9129 (50 IPs across Canada and UK)
#
# Usage:
#   chmod +x start_torguard_all.sh
#   ./start_torguard_all.sh 'YOUR_TORGUARD_USER:YOUR_TORGUARD_PASS'
#
# Get credentials: log into torguard.net → My Account → Change Passwords
# → set Proxy/SOCKS username and password (different from account login)
#
# To stop: kill $(jobs -p)

set -euo pipefail

CREDS="${1:?Usage: $0 TORGUARD_USER:TORGUARD_PASS}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# All 50 working IPs (excluding dead subnets 77.243.189.x and 146.70.27.242-246)
IPS=(
    # Canada - Montreal (89.47.234.x)
    89.47.234.26 89.47.234.27 89.47.234.28 89.47.234.29 89.47.234.30
    89.47.234.74 89.47.234.75 89.47.234.76 89.47.234.77 89.47.234.78
    # Canada - Montreal (86.106.90.x)
    86.106.90.226 86.106.90.227 86.106.90.228 86.106.90.229 86.106.90.230
    # Canada - Montreal (146.70.27.x)
    146.70.27.218 146.70.27.219 146.70.27.220 146.70.27.221 146.70.27.222
    146.70.27.250 146.70.27.251 146.70.27.252 146.70.27.253 146.70.27.254
    # Canada - Montreal (176.113.74.x)
    176.113.74.74 176.113.74.75 176.113.74.76 176.113.74.77 176.113.74.78
    176.113.74.130 176.113.74.131 176.113.74.132 176.113.74.133 176.113.74.134
    176.113.74.138 176.113.74.139 176.113.74.140 176.113.74.141 176.113.74.142
    # UK - London (146.70.95.x)
    146.70.95.26 146.70.95.27 146.70.95.28 146.70.95.29 146.70.95.30
    146.70.95.74 146.70.95.75 146.70.95.76 146.70.95.77 146.70.95.78
)

PORT=9080
for ip in "${IPS[@]}"; do
    python "$SCRIPT_DIR/socks_to_http_proxy.py" \
        --socks "socks5h://${CREDS}@${ip}:1080" \
        --port "$PORT" &
    PORT=$((PORT + 1))
done

echo ""
echo "Started ${#IPS[@]} Torguard proxies on ports 9080-$((PORT - 1))"
echo "Press Ctrl+C to stop all."
wait
