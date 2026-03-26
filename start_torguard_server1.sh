#!/usr/bin/env bash
# Server 1: 18 Torguard IPs on their assigned ports (9080-9094, 9120-9122)
# These ports match the TORGUARD_PROXIES dict in download_clips.py
set -euo pipefail
CREDS="${1:?Usage: $0 TORGUARD_USER:TORGUARD_PASS}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

declare -A PROXIES=(
    # Canada - Montreal (89.47.234.x)
    [9080]="89.47.234.26" [9081]="89.47.234.27" [9082]="89.47.234.28"
    [9083]="89.47.234.29" [9084]="89.47.234.30" [9085]="89.47.234.74"
    [9086]="89.47.234.75" [9087]="89.47.234.76" [9088]="89.47.234.77"
    [9089]="89.47.234.78"
    # Canada - Montreal (86.106.90.x)
    [9090]="86.106.90.226" [9091]="86.106.90.227" [9092]="86.106.90.228"
    [9093]="86.106.90.229" [9094]="86.106.90.230"
    # UK - London
    [9120]="146.70.95.26" [9121]="146.70.95.27" [9122]="146.70.95.28"
)

for port in $(echo "${!PROXIES[@]}" | tr ' ' '\n' | sort -n); do
    ip="${PROXIES[$port]}"
    python "$SCRIPT_DIR/socks_to_http_proxy.py" --socks "socks5h://${CREDS}@${ip}:1080" --port "$port" &
done

echo "Server 1: Started ${#PROXIES[@]} Torguard proxies"
echo "Press Ctrl+C to stop."
wait
