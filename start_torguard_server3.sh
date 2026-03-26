#!/usr/bin/env bash
# Server 3: 14 Torguard IPs on their assigned ports (9110-9119, 9126-9129)
# These ports match the TORGUARD_PROXIES dict in download_clips.py
set -euo pipefail
CREDS="${1:?Usage: $0 TORGUARD_USER:TORGUARD_PASS}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

declare -A PROXIES=(
    # Canada - Montreal (176.113.74.x)
    [9110]="176.113.74.130" [9111]="176.113.74.131" [9112]="176.113.74.132"
    [9113]="176.113.74.133" [9114]="176.113.74.134" [9115]="176.113.74.138"
    [9116]="176.113.74.139" [9117]="176.113.74.140" [9118]="176.113.74.141"
    [9119]="176.113.74.142"
    # UK - London
    [9126]="146.70.95.75" [9127]="146.70.95.76" [9128]="146.70.95.77"
    [9129]="146.70.95.78"
)

for port in $(echo "${!PROXIES[@]}" | tr ' ' '\n' | sort -n); do
    ip="${PROXIES[$port]}"
    python "$SCRIPT_DIR/socks_to_http_proxy.py" --socks "socks5h://${CREDS}@${ip}:1080" --port "$port" &
done

echo "Server 3: Started ${#PROXIES[@]} Torguard proxies"
echo "Press Ctrl+C to stop."
wait
