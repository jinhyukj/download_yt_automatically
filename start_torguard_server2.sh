#!/usr/bin/env bash
# Server 2: 18 Torguard IPs on their assigned ports (9095-9109, 9123-9125)
# These ports match the TORGUARD_PROXIES dict in download_clips.py
set -euo pipefail
CREDS="${1:?Usage: $0 TORGUARD_USER:TORGUARD_PASS}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

declare -A PROXIES=(
    # Canada - Montreal (146.70.27.x)
    [9095]="146.70.27.218" [9096]="146.70.27.219" [9097]="146.70.27.220"
    [9098]="146.70.27.221" [9099]="146.70.27.222" [9100]="146.70.27.250"
    [9101]="146.70.27.251" [9102]="146.70.27.252" [9103]="146.70.27.253"
    [9104]="146.70.27.254"
    # Canada - Montreal (176.113.74.x)
    [9105]="176.113.74.74" [9106]="176.113.74.75" [9107]="176.113.74.76"
    [9108]="176.113.74.77" [9109]="176.113.74.78"
    # UK - London
    [9123]="146.70.95.29" [9124]="146.70.95.30" [9125]="146.70.95.74"
)

for port in $(echo "${!PROXIES[@]}" | tr ' ' '\n' | sort -n); do
    ip="${PROXIES[$port]}"
    python "$SCRIPT_DIR/socks_to_http_proxy.py" --socks "socks5h://${CREDS}@${ip}:1080" --port "$port" &
done

echo "Server 2: Started ${#PROXIES[@]} Torguard proxies"
echo "Press Ctrl+C to stop."
wait
