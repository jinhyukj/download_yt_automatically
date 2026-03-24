#!/usr/bin/env bash
# Start all NordVPN SOCKS5-to-HTTP proxy bridges.
# Replace USER:PASS with your NordVPN service credentials.
#
# Each proxy bridges a different NordVPN region to a local HTTP port.
# The download pipeline round-robins across these ports.
#
# Usage:
#   chmod +x start_proxies.sh
#   ./start_proxies.sh USER:PASS
#
# To stop all proxies: kill $(jobs -p)

set -euo pipefail

CREDS="${1:?Usage: $0 USER:PASS}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

declare -A REGIONS=(
    ["new-york.us.socks.nordhold.net"]=8080
    ["los-angeles.us.socks.nordhold.net"]=8081
    ["chicago.us.socks.nordhold.net"]=8082
    ["dallas.us.socks.nordhold.net"]=8083
    ["atlanta.us.socks.nordhold.net"]=8084
    ["san-francisco.us.socks.nordhold.net"]=8085
    ["phoenix.us.socks.nordhold.net"]=8086
    ["amsterdam.nl.socks.nordhold.net"]=8087
    ["stockholm.se.socks.nordhold.net"]=8088
)

for host in "${!REGIONS[@]}"; do
    port="${REGIONS[$host]}"
    echo "Starting proxy: $host → http://127.0.0.1:$port"
    python "$SCRIPT_DIR/socks_to_http_proxy.py" \
        --socks "socks5h://${CREDS}@${host}:1080" \
        --port "$port" &
done

echo ""
echo "All proxies started. Press Ctrl+C to stop."
wait
