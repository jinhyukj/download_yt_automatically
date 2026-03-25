#!/usr/bin/env python3
"""
download_clips.py
──────────────────
Fast parallel YouTube clip downloader with:
  - Round-robin proxy rotation (NordVPN SOCKS5 via socks_to_http_proxy.py)
  - Round-robin cookie rotation (multiple YouTube account cookies)
  - Slack webhook progress notifications every N videos
  - Permanent failure tracking (skip videos that can never be downloaded)
  - Resume support (skip already-downloaded clips)
  - Video-only output in a flat directory

Usage example:
    python download_clips.py \
        --input ./filtered_video_clips.json \
        --output ./videos_output \
        --cookies-dir ./cookies_pool \
        --proxy-list new-york,los-angeles,chicago,dallas,atlanta,san-francisco,phoenix,amsterdam,stockholm \
        --proxy-creds 'USER:PASS' \
        --workers 18 \
        --slack-webhook "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
"""

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple


# ── Constants ────────────────────────────────────────────────────────────────

PERMANENT_ERROR_PHRASES = [
    "video unavailable",
    "account associated with this video has been terminated",
    "private video",
    "video is private",
    "user has closed their youtube account",
    "this video has been removed",
    "this video is no longer available",
    "video has been removed by the uploader",
    "terms of service",
    "copyright",
    "community guidelines",
    "requested format is not available",
]

TRANSIENT_ERROR_PHRASES = [
    "page needs to be reloaded",
    "http error 403",
    "http error 429",
    "forbidden",
    "too many requests",
    "sign in to confirm",
    "confirm you're not a robot",
    "captcha",
    "cookie",
    "login required",
    "socks",
    "proxy",
    "timeout",
    "connection",
    "network",
    "unusual traffic",
    "temporarily blocked",
    "ffmpeg exited",
]

PROXY_HOSTNAMES = {
    "new-york": ("new-york.us.socks.nordhold.net", 8080),
    "los-angeles": ("los-angeles.us.socks.nordhold.net", 8081),
    "chicago": ("chicago.us.socks.nordhold.net", 8082),
    "dallas": ("dallas.us.socks.nordhold.net", 8083),
    "atlanta": ("atlanta.us.socks.nordhold.net", 8084),
    "san-francisco": ("san-francisco.us.socks.nordhold.net", 8085),
    "phoenix": ("phoenix.us.socks.nordhold.net", 8086),
    "amsterdam": ("amsterdam.nl.socks.nordhold.net", 8087),
    "stockholm": ("stockholm.se.socks.nordhold.net", 8088),
    "us": ("us.socks.nordhold.net", 8080),
    "nl": ("nl.socks.nordhold.net", 8087),
    "se": ("se.socks.nordhold.net", 8088),
}

FFMPEG_WRAPPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg_wrapper")

SLACK_REPORT_INTERVAL = 10  # Send Slack update every N URLs processed


# ── Helpers ──────────────────────────────────────────────────────────────────

def cleanup_stale_parts(output_dir: str, max_age_hours: int = 24) -> int:
    """Remove .part files older than max_age_hours. Returns count of deleted files."""
    if not os.path.isdir(output_dir):
        return 0
    now = time.time()
    max_age_sec = max_age_hours * 3600
    deleted = 0
    for f in os.listdir(output_dir):
        if f.endswith(".part") or f.endswith(".part-Frag0"):
            fp = os.path.join(output_dir, f)
            try:
                age = now - os.path.getmtime(fp)
                if age > max_age_sec:
                    os.remove(fp)
                    deleted += 1
            except OSError:
                pass
    return deleted


def get_video_id(url: str) -> str:
    if "watch?v=" in url:
        return url.split("watch?v=")[-1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1].split("?")[0]
    if "/shorts/" in url:
        return url.split("/shorts/")[-1].split("?")[0]
    return url.split("/")[-1] or "unknown_id"


def safe_mkdir(path: str) -> None:
    if path:
        os.makedirs(path, exist_ok=True)


def seconds_to_time_string(seconds_value: float) -> str:
    if seconds_value < 0:
        seconds_value = 0.0
    ms = math.floor(seconds_value * 1000 + 1e-6)
    hours, rem = divmod(ms, 3_600_000)
    minutes, ms = divmod(rem, 60_000)
    seconds, ms = divmod(ms, 1000)
    if ms == 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


def classify_failure(error_msg: str) -> str:
    msg = error_msg.lower()
    if any(phrase in msg for phrase in PERMANENT_ERROR_PHRASES):
        return "permanent"
    if any(phrase in msg for phrase in TRANSIENT_ERROR_PHRASES):
        return "transient"
    return "unknown"


def categorize_error_for_slack(error_msg: str) -> str:
    """Return a short human-readable error category for Slack reporting."""
    msg = error_msg.lower()
    if "video unavailable" in msg:
        return "video unavailable"
    if "account associated" in msg or "terminated" in msg:
        return "account terminated"
    if "private video" in msg or "video is private" in msg:
        return "private video"
    if "removed" in msg:
        return "video removed"
    if "copyright" in msg:
        return "copyright"
    if "requested format is not available" in msg:
        return "no video streams"
    if "terms of service" in msg or "community guidelines" in msg:
        return "policy violation"
    if "cookie" in msg or "login required" in msg or "sign in" in msg:
        return "expired cookie"
    if "socks" in msg:
        return "socks error"
    if "proxy" in msg:
        return "proxy error"
    if "403" in msg or "forbidden" in msg:
        return "HTTP 403"
    if "429" in msg or "too many requests" in msg or "unusual traffic" in msg:
        return "rate limited"
    if "timeout" in msg:
        return "timeout"
    if "connection" in msg or "network" in msg:
        return "network error"
    if "captcha" in msg or "robot" in msg:
        return "captcha"
    if "ffmpeg" in msg:
        return "ffmpeg error"
    return "other"


# ── Slack ────────────────────────────────────────────────────────────────────

def send_slack(webhook_url: Optional[str], text: str) -> None:
    if not webhook_url:
        return
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception:
        pass


# ── Permanent failure tracking ───────────────────────────────────────────────

def load_permanent_failures(path: str) -> set:
    urls = set()
    if not os.path.exists(path):
        return urls
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if parts:
                    urls.add(parts[0])
    except Exception:
        pass
    return urls


def append_permanent_failure(path: str, url: str, reason: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{url}\t{reason}\t{datetime.now().isoformat()}\n")


# ── Resume: check if clip already downloaded ─────────────────────────────────

def is_clip_downloaded(video_id: str, start: float, end: float, output_dir: str) -> bool:
    """Check if a clip was already successfully downloaded via its JSON log."""
    log_filename = f"{video_id}_{start:.3f}_{end:.3f}.json".replace(":", "-")
    log_file = os.path.join(output_dir, "json_logs", log_filename)
    if not os.path.exists(log_file):
        return False
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("download_info", {}).get("status") == "success":
            vf = data.get("download_info", {}).get("video_clip_file", "")
            return bool(vf and os.path.exists(vf) and os.path.getsize(vf) > 0)
    except Exception:
        pass
    return False


# ── Input parsing ────────────────────────────────────────────────────────────

def iter_segments_from_json(
    path: str,
) -> Generator[Tuple[str, float, float, str], None, None]:
    """Yield (url, start, end, clip_id) from the filtered_video_clips.json."""
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list):
        raise ValueError("Expected top-level JSON array")
    for item in items:
        if not isinstance(item, dict):
            continue
        clip_id = item.get("id", "")
        info = item.get("info", {})
        url = info.get("Video Link") or info.get("video_link")
        start = item.get("start-time") or item.get("start")
        end = item.get("end-time") or item.get("end")
        if url is None or start is None or end is None:
            continue
        try:
            sf, ef = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if ef > sf:
            yield url, sf, ef, clip_id


# ── Cookie pool ──────────────────────────────────────────────────────────────

def load_cookie_pool(cookies_dir: Optional[str], single_cookie: Optional[str]) -> List[str]:
    """
    Build a list of cookie file paths.
    Priority: cookies_dir (all .txt files) > single_cookie path.
    """
    pool: List[str] = []
    if cookies_dir and os.path.isdir(cookies_dir):
        for f in sorted(os.listdir(cookies_dir)):
            if f.endswith(".txt"):
                fp = os.path.join(cookies_dir, f)
                if os.path.getsize(fp) > 0:
                    pool.append(fp)
    if not pool and single_cookie and os.path.exists(single_cookie):
        pool.append(single_cookie)
    return pool


# ── Proxy configs ────────────────────────────────────────────────────────────

def build_proxy_configs(
    proxy_list: Optional[str],
    proxy_creds: Optional[str],
    single_proxy: Optional[str],
) -> List[Tuple[str, int]]:
    """Return list of (socks5_url, http_proxy_port) tuples.

    yt-dlp uses the socks5h URL directly (it has native SOCKS5 support).
    ffmpeg uses the HTTP bridge (socks_to_http_proxy.py) on the given port.
    """
    if proxy_list and proxy_creds:
        configs = []
        for name in proxy_list.split(","):
            name = name.strip()
            if name in PROXY_HOSTNAMES:
                hostname, port = PROXY_HOSTNAMES[name]
                url = f"socks5h://{proxy_creds}@{hostname}:1080"
                configs.append((url, port))
            else:
                print(f"Warning: unknown proxy name '{name}', skipping")
        return configs
    if single_proxy:
        return [(single_proxy, 8080)]
    return []


def check_proxy_health(proxy_configs: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
    """Test each proxy and return only the working ones."""
    if not proxy_configs:
        return proxy_configs
    import urllib.request as ur
    healthy = []
    for proxy_url, port in proxy_configs:
        http_bridge = f"http://127.0.0.1:{port}"
        try:
            handler = ur.ProxyHandler({"http": http_bridge, "https": http_bridge})
            opener = ur.build_opener(handler)
            resp = opener.open("http://httpbin.org/ip", timeout=8)
            resp.read()
            healthy.append((proxy_url, port))
        except Exception as e:
            host = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
            print(f"  DEAD: {host} (port {port}) — {e}")
    return healthy


class ProxyPool:
    """Thread-safe proxy pool with periodic background health checks.

    Workers call pick() to get the next proxy via round-robin (only from
    healthy proxies).  A background thread re-checks every `interval`
    seconds, removing dead proxies and re-adding recovered ones.
    """

    def __init__(
        self,
        all_configs: List[Tuple[str, int]],
        max_per_proxy: int = 2,
        check_interval: int = 300,  # seconds (default 5 min)
        slack_webhook: Optional[str] = None,
    ):
        self._all = list(all_configs)  # full list (never changes)
        self._lock = threading.Lock()
        self._counter = 0
        self._healthy: List[Tuple[str, int]] = []
        self._semaphores: Dict[int, threading.Semaphore] = {}
        self._max_per_proxy = max_per_proxy
        self._check_interval = check_interval
        self._slack_webhook = slack_webhook
        self._stop_event = threading.Event()
        self._bg_thread: Optional[threading.Thread] = None

        # Initial health check
        self._recheck()

    def _recheck(self) -> None:
        """Run health check and update the healthy list."""
        new_healthy = check_proxy_health(self._all)
        with self._lock:
            old_ports = {p for _, p in self._healthy}
            new_ports = {p for _, p in new_healthy}
            self._healthy = new_healthy
            # Create semaphores for any newly healthy proxy
            for _, port in new_healthy:
                if port not in self._semaphores:
                    self._semaphores[port] = threading.Semaphore(self._max_per_proxy)

        added = new_ports - old_ports
        removed = old_ports - new_ports
        if added or removed:
            changes = []
            if added:
                changes.append(f"recovered: {added}")
            if removed:
                changes.append(f"died: {removed}")
            msg = f"Proxy recheck: {len(new_healthy)}/{len(self._all)} healthy ({', '.join(changes)})"
            print(f"[proxy-pool] {msg}")
            send_slack(self._slack_webhook, f":arrows_counterclockwise: {msg}")

    def _bg_loop(self) -> None:
        """Background thread: periodically recheck proxy health."""
        while not self._stop_event.wait(self._check_interval):
            try:
                self._recheck()
            except Exception as e:
                print(f"[proxy-pool] recheck error: {e}")

    def start(self) -> None:
        """Start background health-check thread."""
        if self._bg_thread is not None:
            return
        self._bg_thread = threading.Thread(target=self._bg_loop, daemon=True)
        self._bg_thread.start()

    def stop(self) -> None:
        """Stop background health-check thread."""
        self._stop_event.set()
        if self._bg_thread:
            self._bg_thread.join(timeout=5)

    def pick(self) -> Tuple[Optional[str], Optional[int]]:
        """Pick the next healthy proxy (round-robin). Returns (url, port) or (None, None)."""
        with self._lock:
            if not self._healthy:
                return None, None
            idx = self._counter % len(self._healthy)
            self._counter += 1
            return self._healthy[idx]

    def get_semaphore(self, port: int) -> Optional[threading.Semaphore]:
        """Get the semaphore for a proxy port."""
        with self._lock:
            return self._semaphores.get(port)

    @property
    def healthy_count(self) -> int:
        with self._lock:
            return len(self._healthy)

    @property
    def total_count(self) -> int:
        return len(self._all)


# ── yt-dlp command builder ───────────────────────────────────────────────────

def build_ytdlp_base(
    cookie_path: Optional[str],
    browser: Optional[str],
    proxy: Optional[str] = None,
) -> Tuple[Optional[List[str]], Optional[str]]:
    """Build the base yt-dlp command. Returns (cmd, error)."""
    try:
        import importlib.util
        if importlib.util.find_spec("yt_dlp") is not None:
            base = [sys.executable, "-m", "yt_dlp"]
        else:
            raise ImportError
    except Exception:
        exe = shutil.which("yt-dlp")
        if exe is None:
            return None, "yt-dlp not found"
        base = [exe]

    if browser:
        base.extend(["--cookies-from-browser", browser])
    elif cookie_path and os.path.exists(cookie_path):
        base.extend(["--cookies", cookie_path])

    if proxy:
        base.extend(["--proxy", proxy])
        if os.path.isdir(FFMPEG_WRAPPER_DIR):
            base.extend(["--ffmpeg-location", FFMPEG_WRAPPER_DIR])

    base.extend(["--js-runtimes", "node", "--remote-components", "ejs:github"])
    base.extend(["-4", "--ignore-config"])
    return base, None


# ── Single-URL download function (called by workers) ────────────────────────


def _run_ytdlp_once(
    url: str,
    section_args: List[str],
    output_dir: str,
    cookie_path: Optional[str],
    browser: Optional[str],
    proxy_url: Optional[str],
    http_proxy_port: Optional[int],
    extractor_args: Optional[str],
) -> Tuple[int, str]:
    """Single yt-dlp invocation. Returns (return_code, stdout_or_error)."""
    base_cmd, err = build_ytdlp_base(cookie_path, browser, proxy_url)
    if base_cmd is None:
        return 1, err or "yt-dlp not found"

    output_template = os.path.join(
        output_dir,
        "%(id)s_%(section_start).3f_%(section_end).3f.%(ext)s",
    )

    cmd = [
        *base_cmd,
        "--no-playlist",
        "--retries", "3",
        "--fragment-retries", "3",
        # No -N or --concurrent-fragments: keep 1 connection per worker
        # to avoid overwhelming SOCKS proxies (NordVPN throttles on too many connections)
        "--no-warnings",
        "--restrict-filenames",
        "--continue", "--no-overwrites",
        "--print", "after_move:filepath",
        "--no-write-subs",
        "--no-write-auto-subs",
        "--no-write-description",
        "--no-keep-fragments",
        "--clean-info-json",
        "-o", output_template,
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[vcodec!=none]/best",
        "--merge-output-format", "mp4",
        "--force-keyframes-at-cuts",
    ]

    if extractor_args:
        cmd.extend(["--extractor-args", extractor_args])
    cmd.extend(section_args)
    cmd.append(url)

    env = None
    if http_proxy_port is not None:
        env = os.environ.copy()
        env["FFMPEG_HTTP_PROXY"] = f"http://127.0.0.1:{http_proxy_port}"

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=600,
        )
        if proc.returncode == 0:
            return 0, proc.stdout.strip()
        err_msg = (proc.stderr.strip() or proc.stdout.strip())
        return proc.returncode, err_msg
    except subprocess.TimeoutExpired:
        return 1, "timeout: download took longer than 10 minutes"
    except Exception as exc:
        return 1, f"yt-dlp failed: {exc}"


def download_one_url(
    url: str,
    segments: List[Tuple[float, float]],
    output_dir: str,
    cookie_pool: List[str],
    browser: Optional[str],
    proxy_pool: Optional["ProxyPool"],
    extractor_args: Optional[str],
    max_retries: int = 5,
    _cookie_counter: Optional[List[int]] = None,
    _counter_lock: Optional[threading.Lock] = None,
) -> Tuple[int, str]:
    """
    Download all segments for one URL with retry logic.
    On transient failures, retries with a different proxy.
    Uses ProxyPool for round-robin + per-proxy semaphores + live health checks.
    Returns (return_code, stdout_or_error, method) where method describes how it was downloaded.
    """
    # Build section args
    section_args: List[str] = []
    for s, e in segments:
        if e <= s:
            continue
        section_args.extend([
            "--download-sections",
            f"*{seconds_to_time_string(s)}-{seconds_to_time_string(e)}",
        ])
    if not section_args:
        return 1, "No valid segments", "none"

    def pick_proxy():
        if proxy_pool is None:
            return None, None
        return proxy_pool.pick()

    def pick_cookie():
        if not cookie_pool:
            return None
        if _counter_lock and _cookie_counter is not None:
            with _counter_lock:
                idx = _cookie_counter[0]
                _cookie_counter[0] += 1
            return cookie_pool[idx % len(cookie_pool)]
        return random.choice(cookie_pool)

    def run_with_semaphore(cookie, browser, proxy_url, http_port, extractor_args):
        """Run yt-dlp, acquiring the per-proxy semaphore first."""
        sem = None
        if proxy_pool and http_port is not None:
            sem = proxy_pool.get_semaphore(http_port)
        if sem:
            sem.acquire()
        try:
            return _run_ytdlp_once(
                url, section_args, output_dir,
                cookie, browser, proxy_url, http_port, extractor_args,
            )
        finally:
            if sem:
                sem.release()

    last_err = ""
    for attempt in range(max_retries):
        proxy_url, http_port = pick_proxy()

        # Always try without cookie files — cookies cause YouTube to restrict formats.
        rc, msg = run_with_semaphore(
            None, browser, proxy_url, http_port, extractor_args,
        )
        if rc == 0:
            return 0, msg, "proxy"

        last_err = msg
        failure_type = classify_failure(msg)
        if failure_type == "permanent":
            return rc, msg, "proxy"

        # Transient: backoff with longer waits to let NordVPN recover
        if attempt < max_retries - 1:
            wait = (3 ** attempt) + random.uniform(2, 5)
            time.sleep(wait)

    # Fallback 1: try WITHOUT proxy (direct IP).
    # "Page needs to be reloaded" and "Sign in to confirm" are proxy-IP-based
    # bot detection. The server's direct IP is often not flagged.
    rc, msg = _run_ytdlp_once(
        url, section_args, output_dir,
        None, browser, None, None, extractor_args,
    )
    if rc == 0:
        return 0, msg, "direct"
    if classify_failure(msg) == "permanent":
        return rc, msg, "direct"

    # Fallback 2: try WITH a cookie (for age-restricted etc.)
    cookie = pick_cookie()
    if cookie:
        proxy_url, http_port = pick_proxy()
        rc, msg = run_with_semaphore(
            cookie, browser, proxy_url, http_port, extractor_args,
        )
        if rc == 0:
            return 0, msg, "proxy+cookie"
        # "format not available" from cookie is a cookie problem, not permanent
        if "requested format is not available" in msg.lower():
            return 1, last_err, "proxy+cookie"
        last_err = msg

    return 1, last_err, "failed"


# ── Stats tracker (thread-safe) ──────────────────────────────────────────────

class DownloadStats:
    def __init__(self):
        self._lock = threading.Lock()
        self.urls_processed = 0
        self.urls_downloaded = 0
        self.segments_downloaded = 0
        self.segments_skipped_permanent = 0
        self.segments_skipped_resume = 0
        self.failure_categories: Dict[str, int] = defaultdict(int)
        # Store (video_id, raw_error) for uncategorized failures so Slack can show them
        self.uncategorized_failures: List[Tuple[str, str]] = []
        # Per-method download counts (proxy, direct, proxy+cookie)
        self.method_counts: Dict[str, int] = defaultdict(int)
        # Per-interval tracking (reset after each Slack update)
        self.interval_segments_downloaded = 0
        self.interval_method_counts: Dict[str, int] = defaultdict(int)
        self.interval_failure_categories: Dict[str, int] = defaultdict(int)
        self.start_time = datetime.now()

    def record_success(self, num_segments: int, method: str = "proxy") -> None:
        with self._lock:
            self.urls_processed += 1
            self.urls_downloaded += 1
            self.segments_downloaded += num_segments
            self.method_counts[method] += num_segments
            self.interval_segments_downloaded += num_segments
            self.interval_method_counts[method] += num_segments

    def record_failure(self, error_msg: str, num_segments: int, video_id: str = "") -> None:
        with self._lock:
            self.urls_processed += 1
            category = categorize_error_for_slack(error_msg)
            self.failure_categories[category] += num_segments
            self.interval_failure_categories[category] += num_segments
            if category == "other":
                short_err = error_msg[:200].replace("\n", " ")
                self.uncategorized_failures.append((video_id, short_err))

    def record_permanent_skip(self, num_segments: int) -> None:
        with self._lock:
            self.urls_processed += 1
            self.segments_skipped_permanent += num_segments

    def record_resume_skip(self, num_segments: int) -> None:
        with self._lock:
            self.segments_skipped_resume += num_segments

    def reset_interval(self) -> None:
        """Reset per-interval counters after a Slack update."""
        with self._lock:
            self.interval_segments_downloaded = 0
            self.interval_method_counts.clear()
            self.interval_failure_categories.clear()

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            return {
                "urls_processed": self.urls_processed,
                "urls_downloaded": self.urls_downloaded,
                "segments_downloaded": self.segments_downloaded,
                "segments_skipped_permanent": self.segments_skipped_permanent,
                "segments_skipped_resume": self.segments_skipped_resume,
                "failure_categories": dict(self.failure_categories),
                "uncategorized_failures": list(self.uncategorized_failures),
                "method_counts": dict(self.method_counts),
                "interval_segments_downloaded": self.interval_segments_downloaded,
                "interval_method_counts": dict(self.interval_method_counts),
                "interval_failure_categories": dict(self.interval_failure_categories),
                "elapsed_seconds": elapsed,
            }


def _format_method_counts(method_counts: dict) -> str:
    """Format method counts like 'proxy: 15, direct: 3, proxy+cookie: 1'."""
    if not method_counts:
        return "none"
    parts = []
    for method in ["proxy", "direct", "proxy+cookie"]:
        if method in method_counts:
            parts.append(f"{method}: {method_counts[method]}")
    return ", ".join(parts) if parts else "none"


def format_slack_update(stats: dict, total_urls: int, is_final: bool = False) -> str:
    header = ":white_check_mark: *Download Complete*" if is_final else ":arrows_counterclockwise: *Download Progress*"
    elapsed_min = stats["elapsed_seconds"] / 60

    lines = [
        header,
        f"URLs processed: {stats['urls_processed']}/{total_urls}",
        f"Clips downloaded: {stats['segments_downloaded']}",
        f"Skipped (already done): {stats['segments_skipped_resume']}",
        f"Skipped (permanently unavailable): {stats['segments_skipped_permanent']}",
        f"Elapsed: {elapsed_min:.1f} min",
    ]

    # Download method breakdown (cumulative)
    method_counts = stats.get("method_counts", {})
    if method_counts:
        lines.append(f"Download methods: {_format_method_counts(method_counts)}")

    # Per-interval stats (what happened since last Slack update)
    interval_dl = stats.get("interval_segments_downloaded", 0)
    interval_methods = stats.get("interval_method_counts", {})
    interval_failures = stats.get("interval_failure_categories", {})
    if not is_final and (interval_dl > 0 or interval_failures):
        lines.append("")
        lines.append(f"*This batch:*")
        if interval_dl > 0:
            lines.append(f"  Downloaded: {interval_dl} clips ({_format_method_counts(interval_methods)})")
        if interval_failures:
            fail_parts = [f"{r}: {c}" for r, c in sorted(interval_failures.items(), key=lambda x: -x[1])]
            lines.append(f"  Failed: {', '.join(fail_parts)}")

    # Cumulative failures
    if stats["failure_categories"]:
        lines.append("")
        lines.append("*Total failures by reason:*")
        for reason, count in sorted(stats["failure_categories"].items(), key=lambda x: -x[1]):
            lines.append(f"  • {reason}: {count}")

    total_failed = sum(stats["failure_categories"].values())
    if total_failed:
        lines.append(f"  _Total failed clips: {total_failed}_")

    # Show raw error messages for uncategorized ("other") failures
    uncategorized = stats.get("uncategorized_failures", [])
    if uncategorized:
        lines.append("")
        lines.append("*Uncategorized errors (raw):*")
        for vid, err in uncategorized[-10:]:  # show last 10 at most
            lines.append(f"  `{vid}`: {err}")
        if len(uncategorized) > 10:
            lines.append(f"  _...and {len(uncategorized) - 10} more_")

    return "\n".join(lines)


# ── Main download orchestrator ───────────────────────────────────────────────

def run_downloads(
    input_json: str,
    output_dir: str,
    cookie_pool: List[str],
    browser: Optional[str],
    proxy_configs: List[Tuple[str, int]],
    extractor_args: Optional[str],
    limit: Optional[int],
    workers: int,
    slack_webhook: Optional[str],
    slack_interval: int,
) -> None:
    safe_mkdir(output_dir)
    json_logs_dir = os.path.join(output_dir, "json_logs")
    safe_mkdir(json_logs_dir)

    # Clean up stale .part files from interrupted previous runs (older than 24h)
    stale_count = cleanup_stale_parts(output_dir, max_age_hours=24)
    if stale_count:
        print(f"Cleaned up {stale_count} stale .part files (older than 24h)")

    # Per-run log directory named by start time (e.g. logs/2026-03-24_19-35-12/)
    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logs_dir = os.path.join(output_dir, "logs", run_timestamp)
    safe_mkdir(logs_dir)

    # Per-run log files
    permanent_file = os.path.join(logs_dir, "permanent_failures.txt")
    failed_urls_file = os.path.join(logs_dir, "failed_urls.txt")

    # Also maintain a cumulative permanent_failures.txt at the top level
    # so that future runs can skip known-dead URLs
    cumulative_permanent_file = os.path.join(output_dir, "logs", "permanent_failures.txt")

    # ── Create proxy pool with background health checks ─────────────────
    proxy_pool: Optional[ProxyPool] = None
    if proxy_configs:
        print("Checking proxy health...")
        proxy_pool = ProxyPool(
            all_configs=proxy_configs,
            max_per_proxy=2,
            check_interval=300,  # recheck every 5 minutes
            slack_webhook=slack_webhook,
        )
        if proxy_pool.healthy_count == 0:
            print("ERROR: No working proxies found. Aborting.")
            send_slack(slack_webhook, ":x: *Download aborted*: no working proxies")
            return
        print(f"Healthy proxies: {proxy_pool.healthy_count}/{proxy_pool.total_count}")
        proxy_pool.start()  # start background health-check thread

    # Load permanently failed URLs
    # Load from cumulative file (across all runs)
    perm_failed = load_permanent_failures(cumulative_permanent_file)
    if perm_failed:
        print(f"Loaded {len(perm_failed)} permanently unavailable URLs")

    # ── Parse input & group by URL ───────────────────────────────────────
    url2segments: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    total_segments = 0
    skipped_resume = 0
    count = 0

    for url, start, end, clip_id in iter_segments_from_json(input_json):
        total_segments += 1
        if limit is not None and count >= limit:
            break
        vid = get_video_id(url)
        if is_clip_downloaded(vid, start, end, output_dir):
            skipped_resume += 1
            continue
        url2segments[url].append((start, end))
        count += 1

    print(f"Total segments in JSON: {total_segments}")
    print(f"Skipped (already downloaded): {skipped_resume}")
    print(f"Segments to download: {count} across {len(url2segments)} unique URLs")

    if not url2segments:
        print("Nothing to download.")
        return

    # ── Stats ────────────────────────────────────────────────────────────
    stats = DownloadStats()
    stats.segments_skipped_resume = skipped_resume
    total_urls = len(url2segments)

    # ── Pre-filter permanent failures ────────────────────────────────────
    urls_to_download: Dict[str, List[Tuple[float, float]]] = {}
    for url, segs in url2segments.items():
        if url in perm_failed:
            stats.record_permanent_skip(len(segs))
            continue
        urls_to_download[url] = sorted(set(segs))

    print(f"URLs to attempt: {len(urls_to_download)} (skipped {total_urls - len(urls_to_download)} permanent)")

    # Send start notification
    n_proxies = proxy_pool.healthy_count if proxy_pool else 0
    send_slack(slack_webhook, (
        f":rocket: *Starting download*\n"
        f"URLs: {len(urls_to_download)} | Segments: {count}\n"
        f"Workers: {workers} | Proxies: {n_proxies} (rechecked every 5 min) | Cookie files: {len(cookie_pool)}\n"
        f"Already downloaded: {skipped_resume}"
    ))

    # ── Shared round-robin counter for cookie rotation ────────────────────
    cookie_counter = [0]
    counter_lock = threading.Lock()

    # ── Submit tasks ─────────────────────────────────────────────────────
    last_slack_count = 0

    def maybe_send_slack_update():
        nonlocal last_slack_count
        snap = stats.snapshot()
        if snap["urls_processed"] - last_slack_count >= slack_interval:
            last_slack_count = snap["urls_processed"]
            send_slack(slack_webhook, format_slack_update(snap, total_urls))
            stats.reset_interval()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for url, segs in urls_to_download.items():
            fut = pool.submit(
                download_one_url,
                url, segs, output_dir,
                cookie_pool, browser,
                proxy_pool, extractor_args,
                5,  # max_retries
                cookie_counter, counter_lock,
            )
            futures[fut] = (url, segs)

        for fut in as_completed(futures):
            url, segs = futures[fut]
            video_id = get_video_id(url)
            try:
                rc, msg, method = fut.result()
            except Exception as exc:
                rc, msg, method = 1, f"Exception: {exc}", "failed"

            if rc == 0:
                stats.record_success(len(segs), method=method)
                # Write JSON logs for resume support
                for s, e in segs:
                    # Find the actual video file
                    log_data = {
                        "source_info": {"url": url, "start_time": s, "end_time": e},
                        "download_info": {
                            "status": "success",
                            "video_clip_file": _find_clip_file(output_dir, video_id, s, e),
                            "download_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        },
                    }
                    log_name = f"{video_id}_{s:.3f}_{e:.3f}.json".replace(":", "-")
                    with open(os.path.join(json_logs_dir, log_name), "w", encoding="utf-8") as lf:
                        json.dump(log_data, lf, ensure_ascii=False, indent=2)
            else:
                failure_type = classify_failure(msg)
                stats.record_failure(msg, len(segs), video_id=video_id)
                # Log failure
                with open(failed_urls_file, "a", encoding="utf-8") as furl:
                    furl.write(f"{url}\t{failure_type}\t{msg}\n")
                if failure_type == "permanent":
                    append_permanent_failure(permanent_file, url, msg)
                    append_permanent_failure(cumulative_permanent_file, url, msg)
                print(f"[FAIL:{failure_type}] {video_id} | {categorize_error_for_slack(msg)}")

            maybe_send_slack_update()

    # ── Stop proxy health-check thread ──────────────────────────────────
    if proxy_pool:
        proxy_pool.stop()

    # ── Final report ─────────────────────────────────────────────────────
    final = stats.snapshot()
    summary = format_slack_update(final, total_urls, is_final=True)
    print("\n" + summary)
    send_slack(slack_webhook, summary)


def _find_clip_file(output_dir: str, video_id: str, start: float, end: float) -> str:
    """Try to find the downloaded video file for a given segment."""
    # The file pattern: {id}_{section_number}_{start}_{end}.mp4
    # We search for files matching the video_id and approximate timing
    try:
        for f in os.listdir(output_dir):
            if f.startswith(video_id) and f.endswith(".mp4"):
                # Extract timing from filename
                import re
                m = re.search(r"_(\d+\.\d+)_(\d+\.\d+)\.", f)
                if m:
                    fs, fe = float(m.group(1)), float(m.group(2))
                    if abs(fs - start) < 1.0 and abs(fe - end) < 1.0:
                        return os.path.join(output_dir, f)
    except Exception:
        pass
    return ""


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fast parallel YouTube clip downloader with proxy & cookie rotation."
    )
    p.add_argument(
        "--input", type=str, required=True,
        help="Path to filtered_video_clips.json",
    )
    p.add_argument(
        "--output", type=str, required=True,
        help="Flat output directory for downloaded videos",
    )
    p.add_argument(
        "--workers", type=int, default=18,
        help="Number of parallel download workers (default: 18)",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Max segments to process (for testing)",
    )
    # ── Cookies ──
    p.add_argument(
        "--cookies", type=str, default=None,
        help="Path to a single cookies.txt file",
    )
    p.add_argument(
        "--cookies-dir", type=str, default=None,
        help="Directory containing multiple cookie .txt files (one per account). "
             "Workers are assigned cookies round-robin.",
    )
    p.add_argument(
        "--browser", type=str, default=None,
        choices=["edge", "chrome", "firefox", "chromium", "brave", "vivaldi", "opera"],
        help="Extract cookies from browser instead of file",
    )
    # ── Proxy ──
    p.add_argument(
        "--proxy", type=str, default=None,
        help="Single proxy URL (socks5h://user:pass@host:port)",
    )
    p.add_argument(
        "--proxy-list", type=str, default=None,
        help="Comma-separated proxy region names for round-robin rotation",
    )
    p.add_argument(
        "--proxy-creds", type=str, default=None,
        help="NordVPN SOCKS5 credentials (user:pass)",
    )
    # ── Slack ──
    p.add_argument(
        "--slack-webhook", type=str, default=None,
        help="Slack webhook URL for progress notifications",
    )
    p.add_argument(
        "--slack-interval", type=int, default=SLACK_REPORT_INTERVAL,
        help=f"Send Slack update every N URLs processed (default: {SLACK_REPORT_INTERVAL})",
    )
    # ── Misc ──
    p.add_argument(
        "--extractor-args", type=str, default=None,
        help="Pass through to yt-dlp --extractor-args",
    )
    return p.parse_args()


def main() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found — required for yt-dlp segment cutting")

    args = parse_args()
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] download_clips.py")

    # Build proxy configs
    proxy_configs = build_proxy_configs(args.proxy_list, args.proxy_creds, args.proxy)
    if proxy_configs:
        print(f"Proxies ({len(proxy_configs)}):")
        for pu, pp in proxy_configs:
            host = pu.split("@")[-1] if "@" in pu else pu
            print(f"  {host} → http://127.0.0.1:{pp}")

    # Build cookie pool
    cookie_pool = load_cookie_pool(args.cookies_dir, args.cookies)
    if cookie_pool:
        print(f"Cookie pool ({len(cookie_pool)} files):")
        for cp in cookie_pool:
            print(f"  {os.path.basename(cp)}")
    else:
        print("Warning: no cookies configured — some videos may require authentication")

    run_downloads(
        input_json=args.input,
        output_dir=args.output,
        cookie_pool=cookie_pool,
        browser=args.browser,
        proxy_configs=proxy_configs,
        extractor_args=args.extractor_args,
        limit=args.limit,
        workers=args.workers,
        slack_webhook=args.slack_webhook,
        slack_interval=args.slack_interval,
    )


if __name__ == "__main__":
    main()
