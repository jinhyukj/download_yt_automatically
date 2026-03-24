#!/usr/bin/env python3
"""
Cookie Refresher - runs on your local machine (with Chrome/browser).
Periodically exports YouTube cookies and uploads them to the download server.

Usage:
    python cookie_refresher.py \
        --remote-host user@server \
        --remote-path /path/to/cookies_pool/account1.txt \
        --interval 25 \
        --browser chrome

    # Multiple accounts (run in separate terminals):
    python cookie_refresher.py --remote-host user@server --remote-path /path/to/cookies_pool/account1.txt --browser chrome
    python cookie_refresher.py --remote-host user@server --remote-path /path/to/cookies_pool/account2.txt --browser "chrome:Profile 2"
    python cookie_refresher.py --remote-host user@server --remote-path /path/to/cookies_pool/account3.txt --browser "chrome:Profile 3"

Requirements:
    pip install yt-dlp
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime


def export_cookies(output_path: str, browser: str = "chrome") -> bool:
    """Export cookies from browser using yt-dlp's internal cookie extraction.

    The browser argument supports 'browser:profile' syntax (e.g. 'chrome:Profile 2').
    """
    try:
        from yt_dlp.cookies import extract_cookies_from_browser

        # Parse 'browser:profile' syntax (e.g. 'chrome:Profile 2')
        if ":" in browser:
            browser_name, profile = browser.split(":", 1)
            cookie_jar = extract_cookies_from_browser(browser_name, profile=profile)
        else:
            cookie_jar = extract_cookies_from_browser(browser)
        cookie_jar.save(output_path, ignore_discard=True, ignore_expires=True)
        return True
    except ImportError:
        print("yt-dlp not found. Install with: pip install yt-dlp")
        return False
    except Exception as e:
        print(f"API cookie export failed ({e}), trying CLI fallback...")
        return _export_cookies_cli(output_path, browser)


def _export_cookies_cli(output_path: str, browser: str) -> bool:
    """Fallback: use yt-dlp CLI to export cookies via --cookies-from-browser + --cookies."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--cookies-from-browser", browser,
        "--cookies", output_path,
        "--skip-download",
        "--no-warnings",
        "--quiet",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"CLI fallback also failed: {e}")
        return False


def upload_cookies(local_path: str, remote_host: str, remote_path: str) -> bool:
    """Upload cookies file to remote server via SCP."""
    dest = f"{remote_host}:{remote_path}"
    try:
        proc = subprocess.run(
            ["scp", "-q", local_path, dest],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0:
            return True
        print(f"SCP failed: {proc.stderr or proc.stdout}")
        return False
    except subprocess.TimeoutExpired:
        print("SCP timed out after 30s")
        return False
    except Exception as e:
        print(f"SCP error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Periodically export browser cookies and upload to download server."
    )
    parser.add_argument(
        "--remote-host", required=True,
        help="SSH host (e.g., user@server or an SSH config alias)",
    )
    parser.add_argument(
        "--remote-path", required=True,
        help="Remote path for the cookies file",
    )
    parser.add_argument(
        "--interval", type=int, default=25,
        help="Refresh interval in minutes (default: 25)",
    )
    parser.add_argument(
        "--browser", default="chrome",
        help="Browser to extract cookies from (default: chrome). "
             "Supports 'browser:profile' syntax (e.g. 'chrome:Profile 2').",
    )
    parser.add_argument(
        "--local-path", default=None,
        help="Local path to save cookies (default: auto-generated from browser name)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run once and exit (don't loop)",
    )
    args = parser.parse_args()

    if args.local_path:
        cookie_path = args.local_path
    else:
        # Derive unique local filename from browser arg to avoid conflicts
        # when running multiple instances (e.g. chrome -> live_cookies_chrome.txt,
        # chrome:Profile 2 -> live_cookies_chrome_Profile_2.txt)
        safe_name = args.browser.replace(":", "_").replace(" ", "_").replace("/", "_")
        cookie_path = os.path.join(os.getcwd(), f"live_cookies_{safe_name}.txt")

    print("Cookie Refresher")
    print(f"  Browser:  {args.browser}")
    print(f"  Remote:   {args.remote_host}:{args.remote_path}")
    print(f"  Interval: {args.interval} min")
    print(f"  Local:    {cookie_path}")
    print()

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Exporting cookies from {args.browser}...")

        if export_cookies(cookie_path, args.browser):
            size = os.path.getsize(cookie_path)
            print(f"[{now}] Exported ({size} bytes)")

            if upload_cookies(cookie_path, args.remote_host, args.remote_path):
                print(f"[{now}] Uploaded to {args.remote_host}")
            else:
                print(f"[{now}] FAILED to upload!")
        else:
            print(f"[{now}] FAILED to export cookies!")

        if args.once:
            break

        print(f"[{now}] Next refresh in {args.interval} minutes")
        try:
            time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


if __name__ == "__main__":
    main()
