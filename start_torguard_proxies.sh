#!/usr/bin/env bash
# Start Torguard SOCKS5-to-HTTP proxy bridges.
# 10 IPs across 3 regions (Canada, Netherlands, UK).
#
# Usage:
#   chmod +x start_torguard_proxies.sh
#   ./start_torguard_proxies.sh 'YOUR_TORGUARD_USER:YOUR_TORGUARD_PASS'
#
# Ports: 9080-9089
# To stop: kill $(jobs -p)
#
# Get credentials: log into torguard.net → My Account → Change Passwords
# → set Proxy/SOCKS username and password (different from account login)

set -euo pipefail

CREDS="${1:?Usage: $0 TORGUARD_USER:TORGUARD_PASS}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 10 IPs across 3 regions (different subnets for IP diversity)
declare -A PROXIES=(
    # Canada - Montreal (4 IPs from different subnets)
    ["9080"]="89.47.234.26"
    ["9081"]="86.106.90.226"
    ["9082"]="176.113.74.74"
    ["9083"]="146.70.27.218"
    # Netherlands - Amsterdam (3 IPs)
    ["9084"]="77.243.189.162"
    ["9085"]="77.243.189.163"
    ["9086"]="77.243.189.164"
    # UK - London (3 IPs from different subnets)
    ["9087"]="146.70.95.26"
    ["9088"]="146.70.95.74"
    ["9089"]="146.70.95.27"
)

for port in $(echo "${!PROXIES[@]}" | tr ' ' '\n' | sort); do
    ip="${PROXIES[$port]}"
    echo "Starting: $ip:1080 → http://127.0.0.1:$port"
    python "$SCRIPT_DIR/socks_to_http_proxy.py" \
        --socks "socks5h://${CREDS}@${ip}:1080" \
        --port "$port" &
done

echo ""
echo "All Torguard proxies started (ports 9080-9089)."
echo "Press Ctrl+C to stop."
wait
