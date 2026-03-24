# TalkVid YouTube Clip Downloader

Fast parallel YouTube clip downloader with proxy rotation, cookie management, and Slack progress notifications.

Downloads video clips specified in a JSON file using yt-dlp, with:
- **Round-robin proxy rotation** across multiple NordVPN SOCKS5 regions
- **Per-proxy rate limiting** (semaphores) to avoid NordVPN throttling
- **Automatic proxy health checks** every 5 minutes (dead proxies are skipped, recovered ones re-added)
- **Direct-IP fallback** — when all proxies fail for a URL, retries without proxy to bypass proxy-IP-based bot detection
- **Cookie pool support** for age-restricted content (used only as last resort)
- **Resume support** — re-run the same command and already-downloaded clips are skipped
- **Slack webhook notifications** with download progress, failure breakdowns by reason, and raw error messages for uncategorized failures
- **Per-run log files** — each run gets its own timestamped log directory
- **Video-only flat output** — all `.mp4` files in one directory

## Files

| File | Description |
|------|-------------|
| `download_clips.py` | Main download pipeline |
| `socks_to_http_proxy.py` | HTTP-to-SOCKS5 proxy bridge (one per region) |
| `start_proxies.sh` | Helper script to start all 9 proxy bridges at once |
| `cookie_refresher.py` | Runs on your local machine to export & upload fresh cookies |
| `ffmpeg_wrapper/ffmpeg` | Wrapper that injects proxy settings into ffmpeg calls |
| `cookies_pool/` | Directory for cookie files (one per YouTube account) |

## Prerequisites

```bash
pip install yt-dlp PySocks rich
```

You also need:
- **ffmpeg** installed and available in PATH
- **Node.js** installed (used by yt-dlp to solve YouTube challenges)
- A **NordVPN** subscription with SOCKS5 service credentials
- (Optional) A **Slack incoming webhook** URL for notifications

## Setup

### 1. Configure the ffmpeg wrapper

The ffmpeg wrapper injects proxy settings so that ffmpeg downloads video streams through the proxy. You need to point it at your real ffmpeg binary:

```bash
# Find your real ffmpeg path
which ffmpeg
# e.g. /usr/bin/ffmpeg

# Option A: Set the REAL_FFMPEG environment variable
export REAL_FFMPEG=/usr/bin/ffmpeg

# Option B: Create a symlink called ffmpeg.real next to your ffmpeg
sudo ln -s /usr/bin/ffmpeg /usr/local/bin/ffmpeg.real
```

### 2. Start the proxy bridges

Each proxy bridge forwards traffic from a local HTTP port through a NordVPN SOCKS5 endpoint. You need one per region.

**Quick start** (all 9 regions):
```bash
./start_proxies.sh 'YOUR_NORDVPN_USER:YOUR_NORDVPN_PASS'
```

**Manual start** (individual regions):
```bash
# New York on port 8080
python socks_to_http_proxy.py --socks 'socks5h://USER:PASS@new-york.us.socks.nordhold.net:1080' --port 8080

# Los Angeles on port 8081
python socks_to_http_proxy.py --socks 'socks5h://USER:PASS@los-angeles.us.socks.nordhold.net:1080' --port 8081

# ... and so on for each region
```

Available regions and their default ports:

| Region | Hostname | Port |
|--------|----------|------|
| New York | `new-york.us.socks.nordhold.net` | 8080 |
| Los Angeles | `los-angeles.us.socks.nordhold.net` | 8081 |
| Chicago | `chicago.us.socks.nordhold.net` | 8082 |
| Dallas | `dallas.us.socks.nordhold.net` | 8083 |
| Atlanta | `atlanta.us.socks.nordhold.net` | 8084 |
| San Francisco | `san-francisco.us.socks.nordhold.net` | 8085 |
| Phoenix | `phoenix.us.socks.nordhold.net` | 8086 |
| Amsterdam | `amsterdam.nl.socks.nordhold.net` | 8087 |
| Stockholm | `stockholm.se.socks.nordhold.net` | 8088 |

#### How to get NordVPN SOCKS5 credentials

The credentials used here are **not** your NordVPN account email/password. They are separate "service credentials" for manual connections.

1. Log in to [my.nordaccount.com](https://my.nordaccount.com/)
2. Go to **Services** > **NordVPN**
3. Scroll down to **Manual Setup**
4. Select the **OpenVPN / IKEv2** tab (or **Service credentials** depending on the UI version)
5. You will see a **Username** (a long random string like `LTxu...`) and a **Password** — these are your SOCKS5 credentials
6. Use them as `--proxy-creds 'USERNAME:PASSWORD'` in the download command and `USER:PASS` in `start_proxies.sh`

> **Note:** These credentials may change if you regenerate them in the dashboard. If proxies suddenly fail with "SOCKS5 authentication failed", check if your credentials were rotated.

### 3. Set up cookies (optional but recommended)

Cookies are used as a **last resort** when YouTube requires authentication (e.g., age-restricted videos). The pipeline tries without cookies first because cookie files can cause YouTube to restrict available video formats.

#### Single account

Place a Netscape-format cookie file in `cookies_pool/`:
```bash
cookies_pool/
  account1.txt
```

#### Multiple accounts (recommended for heavy downloading)

Use multiple YouTube accounts to spread the load. Each account gets its own cookie file. The pipeline assigns them round-robin.

```bash
cookies_pool/
  account1.txt    # YouTube account 1
  account2.txt    # YouTube account 2
  account3.txt    # YouTube account 3
  ...
```

#### Keeping cookies fresh with cookie_refresher.py

YouTube cookies expire frequently. Run `cookie_refresher.py` **on your local machine** (where you have a browser with YouTube logged in) to periodically export fresh cookies and upload them to the download server.

**Single account:**
```bash
python cookie_refresher.py \
    --remote-host user@your-server \
    --remote-path /path/to/download_yt_automatically/cookies_pool/account1.txt \
    --browser chrome \
    --interval 25
```

**Multiple accounts** — run one instance per Chrome profile, each in a separate terminal:
```bash
# Account 1 (default Chrome profile)
python cookie_refresher.py \
    --remote-host user@server \
    --remote-path /path/to/cookies_pool/account1.txt \
    --browser chrome

# Account 2 (Chrome Profile 2)
python cookie_refresher.py \
    --remote-host user@server \
    --remote-path /path/to/cookies_pool/account2.txt \
    --browser "chrome:Profile 2"

# Account 3 (Chrome Profile 3)
python cookie_refresher.py \
    --remote-host user@server \
    --remote-path /path/to/cookies_pool/account3.txt \
    --browser "chrome:Profile 3"
```

To set up multiple Chrome profiles:
1. Open Chrome, click your profile icon (top right) > **Add**
2. Sign in to a different Google/YouTube account in each profile
3. Check the profile name in `chrome://version/` — it shows the profile directory name (e.g., `Profile 2`, `Profile 3`)

> **Note:** `cookie_refresher.py` requires `yt-dlp` installed on your local machine and SSH access (SCP) to the download server.

## Input JSON Format

The pipeline reads a JSON array where each entry describes a video clip:

```json
[
    {
        "id": "video-dQw4w9WgXcQ-scene1",
        "start-time": 10.5,
        "end-time": 25.0,
        "info": {
            "Video Link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        }
    },
    ...
]
```

Required fields:
- `info.Video Link`: YouTube URL
- `start-time`: Clip start in seconds
- `end-time`: Clip end in seconds

The included dataset is at `../TalkVid_Data/data/filtered_video_clips.json`.

## Running the Pipeline

```bash
python download_clips.py \
    --input ../TalkVid_Data/data/filtered_video_clips.json \
    --output ./videos_output \
    --cookies-dir ./cookies_pool \
    --proxy-list new-york,los-angeles,chicago,dallas,atlanta,san-francisco,phoenix,amsterdam,stockholm \
    --proxy-creds 'YOUR_NORDVPN_USER:YOUR_NORDVPN_PASS' \
    --workers 18 \
    --slack-webhook "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
```

### All Options

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | (required) | Path to input JSON file |
| `--output` | (required) | Output directory for downloaded videos |
| `--workers` | 18 | Number of parallel download workers |
| `--cookies-dir` | None | Directory with cookie `.txt` files |
| `--cookies` | None | Path to a single cookie file |
| `--proxy-list` | None | Comma-separated NordVPN region names |
| `--proxy-creds` | None | NordVPN SOCKS5 credentials (`user:pass`) |
| `--proxy` | None | Single proxy URL (instead of `--proxy-list`) |
| `--slack-webhook` | None | Slack webhook URL for notifications |
| `--slack-interval` | 10 | Send Slack update every N URLs processed |
| `--limit` | None | Max segments to process (for testing) |
| `--browser` | None | Extract cookies from browser directly |
| `--extractor-args` | None | Pass through to yt-dlp `--extractor-args` |

## How the Pipeline Works

### Download flow per URL

Each URL goes through this retry sequence:

```
Attempt 1-5:  Different proxy each time (round-robin) + no cookies
              Exponential backoff between retries (3^n + jitter seconds)
Fallback 1:   Direct IP (no proxy) + no cookies
              Bypasses proxy-IP-based bot detection ("page needs to be reloaded", "sign in")
Fallback 2:   Proxy + cookie from pool
              For age-restricted or auth-required content
```

Permanent errors (video unavailable, account terminated, no video streams) stop retries immediately.

### Proxy management

- **Startup health check**: all proxies are tested before downloading begins; dead ones are excluded
- **Background recheck**: every 5 minutes, all proxies are retested. Dead proxies are removed and recovered proxies are re-added. Changes are reported via Slack.
- **Per-proxy semaphore**: max 2 concurrent downloads per proxy to avoid NordVPN throttling
- **Round-robin assignment**: each retry picks the next proxy in rotation (shared counter across all workers)

### Cookie strategy

Cookies are **avoided by default** because they can cause YouTube to restrict video format availability (returning only storyboard images instead of real video). They are only used as a last-resort fallback after all proxy retries and the direct-IP fallback have failed.

### Resume

The pipeline is fully re-runnable. Just run the same command again:
- Already-downloaded clips are skipped (checked via `json_logs/`)
- Permanently unavailable videos are skipped (checked via cumulative `logs/permanent_failures.txt`)
- Previously-failed transient errors (socks error, rate limit, etc.) are retried

### Slack Notifications

The pipeline sends Slack messages at these points:
- **Start** — URL count, worker/proxy configuration, resume count
- **Every N URLs** (default 10) — progress with per-batch and cumulative stats
- **Proxy health changes** — when the background recheck detects proxies dying or recovering
- **End** — final summary with totals

Each progress update includes:
- **Cumulative totals** — total clips downloaded, skipped, and failed
- **Download methods** — how clips were downloaded across the entire run (`proxy`, `direct`, `proxy+cookie`)
- **This batch** — clips downloaded and failures in the last N URLs since the previous Slack update, with per-method breakdown
- **Failure breakdown** — categorized reasons (e.g., "video unavailable", "socks error", "expired cookie", "rate limited", "no video streams")
- **Uncategorized errors** — raw error messages with video IDs for any "other" failures

Example Slack message:
```
:arrows_counterclockwise: Download Progress
URLs processed: 20/17944
Clips downloaded: 145
Skipped (already done): 257
Skipped (permanently unavailable): 13
Elapsed: 4.2 min
Download methods: proxy: 130, direct: 12, proxy+cookie: 3

This batch:
  Downloaded: 78 clips (proxy: 65, direct: 11, proxy+cookie: 2)
  Failed: socks error: 8, expired cookie: 3

Total failures by reason:
  • socks error: 12
  • expired cookie: 5
  • video unavailable: 3
  Total failed clips: 20
```

## Output Structure

```
videos_output/
  dQw4w9WgXcQ_10.500_25.000.mp4       # Downloaded clips (flat, video-only)
  dQw4w9WgXcQ_30.000_45.500.mp4
  abc123xyz_5.200_18.700.mp4
  ...
  json_logs/                            # Per-clip download logs (for resume, shared across runs)
    dQw4w9WgXcQ_10.500_25.000.json
    ...
  logs/
    permanent_failures.txt              # Cumulative (read on startup to skip known-dead URLs)
    2026-03-24_19-35-12/                # Run 1 logs
      failed_urls.txt
      permanent_failures.txt
    2026-03-24_20-10-45/                # Run 2 logs
      failed_urls.txt
      permanent_failures.txt
```

- **Video files**: all `.mp4` in the root of the output directory (flat, no subdirectories per video)
- **json_logs/**: shared across runs for resume support
- **logs/**: each run creates a timestamped subdirectory with its own `failed_urls.txt` and `permanent_failures.txt`
- **logs/permanent_failures.txt**: cumulative file at the top level, read by future runs to skip known-dead URLs

## Troubleshooting

| Problem | Solution |
|---------|----------|
| All proxies show as DEAD | NordVPN may have temporarily throttled your credentials. Wait 5-10 minutes and try again. |
| "The page needs to be reloaded" | YouTube bot detection on the proxy IP. The pipeline retries with different proxies, then falls back to direct IP (no proxy). |
| "Sign in to confirm you're not a bot" | Same as above — proxy IP flagged. Automatic retry with different proxy + direct-IP fallback. |
| "Requested format is not available" | The video only has storyboard images, no real video streams. Classified as permanent failure, skipped on re-runs. |
| SOCKS errors during download | Too many concurrent connections to NordVPN. The pipeline has per-proxy semaphores (max 2 concurrent) and retries with exponential backoff. |
| Cookies causing "format not available" | Known issue. The pipeline avoids cookies by default. Cookies are only used as a last resort for age-restricted content. |
| "SOCKS5 authentication failed" | NordVPN credentials may have been rotated. Check your service credentials at [my.nordaccount.com](https://my.nordaccount.com/). |
