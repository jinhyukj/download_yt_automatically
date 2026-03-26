#!/usr/bin/env python3
"""
Cookie Refresher v2 - exports YouTube cookies from multiple Chrome profiles
and uploads each as a separate file to the download server with retry logic.

Replaces running multiple cookie_refresher.py instances.

Usage:
    python cookie_refresher_v2.py \
        --remote-host user@server \
        --remote-dir /path/to/cookies_pool \
        --interval 25

Each profile produces a file like:
    live_cookies_chrome_Default.txt
    live_cookies_chrome_Profile_1.txt
    ...

Requirements:
    pip install yt-dlp
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import List, Tuple

# Add your Chrome profile names here.
# Check profile names in chrome://version/ (Profile Path shows the directory name).
PROFILES = [
    "Default",
    # "Profile 1",
    # "Profile 2",
    # "Profile 3",
    # Add more profiles as needed...
]

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


def log(msg: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def _safe_filename(profile: str) -> str:
    """Generate filename matching the cookie_refresher.py convention.

    'chrome:Default'  -> 'live_cookies_chrome_Default.txt'
    'chrome:Profile 1' -> 'live_cookies_chrome_Profile_1.txt'
    """
    browser_arg = f"chrome:{profile}"
    safe_name = browser_arg.replace(":", "_").replace(" ", "_").replace("/", "_")
    return f"live_cookies_{safe_name}.txt"


def export_cookies_for_profile(profile: str, output_path: str) -> bool:
    """Export cookies from a single Chrome profile using yt-dlp API."""
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        cookie_jar = extract_cookies_from_browser("chrome", profile=profile)
        cookie_jar.save(output_path, ignore_discard=True, ignore_expires=True)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
        return False
    except Exception as e:
        log(f"  API export failed for {profile}: {e}")
        return _export_cookies_cli(profile, output_path)


def _export_cookies_cli(profile: str, output_path: str) -> bool:
    """Fallback: use yt-dlp CLI to export cookies."""
    browser_arg = f"chrome:{profile}"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--cookies-from-browser", browser_arg,
        "--cookies", output_path,
        "--skip-download",
        "--no-warnings",
        "--quiet",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        log(f"  CLI fallback failed for {profile}: {e}")
        return False


def upload_with_retry(local_path: str, remote_host: str, remote_path: str) -> bool:
    """Upload cookies file to remote server via SCP with retries."""
    dest = f"{remote_host}:{remote_path}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            proc = subprocess.run(
                ["scp", "-q", "-o", "ConnectTimeout=10", local_path, dest],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode == 0:
                return True
            log(f"  SCP attempt {attempt}/{MAX_RETRIES} failed: {proc.stderr.strip()}")
        except subprocess.TimeoutExpired:
            log(f"  SCP attempt {attempt}/{MAX_RETRIES} timed out")
        except Exception as e:
            log(f"  SCP attempt {attempt}/{MAX_RETRIES} error: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    return False


def refresh_once(
    profiles: List[str],
    remote_host: str,
    remote_dir: str,
    local_dir: str,
) -> Tuple[int, int, int, int]:
    """Run one full refresh cycle.

    Returns (exported_count, uploaded_count, export_failures, upload_failures).
    """
    exported = 0
    uploaded = 0
    export_fails = 0
    upload_fails = 0

    os.makedirs(local_dir, exist_ok=True)

    for profile in profiles:
        filename = _safe_filename(profile)
        local_path = os.path.join(local_dir, filename)
        remote_path = os.path.join(remote_dir, filename)

        # Export with retries
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            if export_cookies_for_profile(profile, local_path):
                success = True
                break
            if attempt < MAX_RETRIES:
                log(f"  Retrying export for {profile} ({attempt}/{MAX_RETRIES})...")
                time.sleep(2)

        if not success:
            export_fails += 1
            log(f"  FAILED to export {profile} after {MAX_RETRIES} attempts")
            continue

        size = os.path.getsize(local_path)
        exported += 1
        log(f"  Exported {profile} -> {filename} ({size} bytes)")

        # Upload with retries
        if upload_with_retry(local_path, remote_host, remote_path):
            uploaded += 1
            log(f"  Uploaded {filename}")
        else:
            upload_fails += 1
            log(f"  FAILED to upload {filename} after {MAX_RETRIES} attempts")

    return exported, uploaded, export_fails, upload_fails


def main():
    parser = argparse.ArgumentParser(
        description="Export cookies from multiple Chrome profiles and upload each separately."
    )
    parser.add_argument(
        "--remote-host", required=True,
        help="SSH host (e.g., user@server or an SSH config alias)",
    )
    parser.add_argument(
        "--remote-dir", required=True,
        help="Remote directory for the cookie files",
    )
    parser.add_argument(
        "--interval", type=int, default=25,
        help="Refresh interval in minutes (default: 25)",
    )
    parser.add_argument(
        "--local-dir", default=None,
        help="Local directory to save cookie files (default: cwd)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run once and exit (don't loop)",
    )
    args = parser.parse_args()

    local_dir = args.local_dir or os.getcwd()

    print("Cookie Refresher v2")
    print(f"  Profiles:   {', '.join(PROFILES)}")
    print(f"  Remote:     {args.remote_host}:{args.remote_dir}")
    print(f"  Local dir:  {local_dir}")
    print(f"  Interval:   {args.interval} min")
    print(f"  Files:      {', '.join(_safe_filename(p) for p in PROFILES)}")
    print(flush=True)

    while True:
        log("Starting refresh cycle...")
        exported, uploaded, export_fails, upload_fails = refresh_once(
            PROFILES, args.remote_host, args.remote_dir, local_dir,
        )

        total = len(PROFILES)
        log(f"Cycle done: {exported}/{total} exported, {uploaded}/{total} uploaded"
            + (f", {export_fails} export failures" if export_fails else "")
            + (f", {upload_fails} upload failures" if upload_fails else ""))

        if args.once:
            sys.exit(0 if (export_fails == 0 and upload_fails == 0) else 1)

        log(f"Next refresh in {args.interval} minutes")
        try:
            time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


if __name__ == "__main__":
    main()
