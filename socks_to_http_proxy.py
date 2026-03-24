"""
Tiny HTTP proxy that forwards all traffic through a SOCKS5 proxy.
This lets tools like ffmpeg (which only support HTTP proxies) use a SOCKS5 proxy.

Usage:
    python socks_to_http_proxy.py --socks 'socks5h://user:pass@host:1080' --port 8080

Then set http_proxy=http://localhost:8080 for ffmpeg.

NordVPN SOCKS5 regions and recommended port mapping:

  - US: new-york(8080), los-angeles(8081), chicago(8082), dallas(8083),
        atlanta(8084), san-francisco(8085), phoenix(8086)
  - NL: amsterdam(8087)
  - SE: stockholm(8088)

Example (replace USER:PASS with your NordVPN service credentials):
    python socks_to_http_proxy.py --socks 'socks5h://USER:PASS@us.socks.nordhold.net:1080' --port 8080
"""

import argparse
import select
import socket
import threading
from urllib.parse import urlparse

import socks  # PySocks


def parse_socks_url(url: str):
    parsed = urlparse(url)
    return {
        "proxy_host": parsed.hostname,
        "proxy_port": parsed.port or 1080,
        "username": parsed.username,
        "password": parsed.password,
        "rdns": parsed.scheme.endswith("h"),  # socks5h = remote DNS
    }


def create_socks_connection(target_host, target_port, socks_config):
    s = socks.socksocket()
    s.set_proxy(
        socks.SOCKS5,
        socks_config["proxy_host"],
        socks_config["proxy_port"],
        rdns=socks_config["rdns"],
        username=socks_config["username"],
        password=socks_config["password"],
    )
    s.settimeout(30)
    s.connect((target_host, target_port))
    return s


def relay(sock_a, sock_b):
    """Relay data between two sockets until one closes."""
    try:
        while True:
            readable, _, _ = select.select([sock_a, sock_b], [], [], 60)
            if not readable:
                break
            for s in readable:
                data = s.recv(65536)
                if not data:
                    return
                other = sock_b if s is sock_a else sock_a
                other.sendall(data)
    except Exception:
        pass
    finally:
        sock_a.close()
        sock_b.close()


def handle_connect(client_sock, target_host, target_port, socks_config):
    """Handle HTTPS CONNECT tunneling."""
    try:
        remote = create_socks_connection(target_host, target_port, socks_config)
        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        relay(client_sock, remote)
    except Exception as e:
        try:
            client_sock.sendall(f"HTTP/1.1 502 Bad Gateway\r\n\r\n{e}".encode())
        except Exception:
            pass
        client_sock.close()


def handle_http(client_sock, request_line, headers_raw, target_host, target_port, socks_config):
    """Handle plain HTTP request by forwarding through SOCKS5."""
    try:
        remote = create_socks_connection(target_host, target_port, socks_config)
        # Reconstruct the request with relative path
        method, url, version = request_line.split(" ", 2)
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        new_request_line = f"{method} {path} {version}\r\n"
        remote.sendall(new_request_line.encode() + headers_raw + b"\r\n")
        relay(client_sock, remote)
    except Exception as e:
        try:
            client_sock.sendall(f"HTTP/1.1 502 Bad Gateway\r\n\r\n{e}".encode())
        except Exception:
            pass
        client_sock.close()


def handle_client(client_sock, socks_config):
    try:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = client_sock.recv(4096)
            if not chunk:
                client_sock.close()
                return
            data += chunk

        header_end = data.index(b"\r\n\r\n")
        header_block = data[:header_end].decode("utf-8", errors="replace")
        lines = header_block.split("\r\n")
        request_line = lines[0]
        headers_raw = data[len(lines[0]) + 2 : header_end + 2]

        method = request_line.split(" ")[0].upper()

        if method == "CONNECT":
            # CONNECT host:port HTTP/1.1
            target = request_line.split(" ")[1]
            if ":" in target:
                host, port = target.rsplit(":", 1)
                port = int(port)
            else:
                host, port = target, 443
            handle_connect(client_sock, host, port, socks_config)
        else:
            # GET http://host:port/path HTTP/1.1
            url = request_line.split(" ")[1]
            parsed = urlparse(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            handle_http(client_sock, request_line, headers_raw, host, port, socks_config)
    except Exception:
        client_sock.close()


def main():
    parser = argparse.ArgumentParser(description="HTTP proxy that forwards through SOCKS5")
    parser.add_argument("--socks", required=True, help="SOCKS5 proxy URL, e.g. socks5h://user:pass@host:1080")
    parser.add_argument("--port", type=int, default=8080, help="Local HTTP proxy port (default: 8080)")
    args = parser.parse_args()

    socks_config = parse_socks_url(args.socks)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", args.port))
    server.listen(64)

    print(f"HTTP proxy listening on 127.0.0.1:{args.port}")
    print(f"Forwarding through SOCKS5: {socks_config['proxy_host']}:{socks_config['proxy_port']}")

    try:
        while True:
            client_sock, _ = server.accept()
            t = threading.Thread(target=handle_client, args=(client_sock, socks_config), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.close()


if __name__ == "__main__":
    main()
