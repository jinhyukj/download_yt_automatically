# TalkVid YouTube Clip Downloader

Fast parallel YouTube clip downloader with proxy rotation, cookie management, and Slack progress notifications.

Downloads video clips specified in a JSON file using yt-dlp, with:
- **Round-robin proxy rotation** across multiple NordVPN SOCKS5 regions
- **Per-proxy rate limiting** to avoid NordVPN throttling
- **Automatic proxy health checks** every 5 minutes (dead proxies are skipped, recovered ones re-added)
- **Cookie pool support** for age-restricted content
- **Resume support** — re-run the same command and already-downloaded clips are skipped
- **Slack webhook notifications** with download progress and failure breakdowns
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

> **Where to find NordVPN credentials**: Log in to your NordVPN account dashboard, go to **Services** > **NordVPN**, and look for "Service credentials" (username and password for manual connections). These are different from your NordVPN account login.

### 3. Set up cookies (optional but recommended)

Cookies are used as a last resort when YouTube requires authentication (e.g., age-restricted videos). The pipeline tries without cookies first because cookie files can cause YouTube to restrict available video formats.

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

### Resume

The pipeline is fully re-runnable. Just run the same command again:
- Already-downloaded clips are skipped (checked via `json_logs/`)
- Permanently unavailable videos are skipped (checked via `logs/permanent_failures.txt`)
- Previously-failed transient errors (socks error, rate limit, etc.) are retried

### Slack Notifications

The pipeline sends Slack messages at these points:
- **Start** — URL count, worker/proxy configuration
- **Every N URLs** (default 10) — progress, downloaded count, failure breakdown by reason
- **Proxy health changes** — when proxies die or recover during the run
- **End** — final summary with totals

Failure reasons are categorized (e.g., "video unavailable", "socks error", "expired cookie", "rate limited"). Uncategorized errors include the raw error message for diagnosis.

## Output Structure

```
videos_output/
  dQw4w9WgXcQ_10.500_25.000.mp4
  dQw4w9WgXcQ_30.000_45.500.mp4
  abc123xyz_5.200_18.700.mp4
  ...
  json_logs/           # Per-clip download logs (for resume)
  logs/
    failed_urls.txt          # All failures with error messages
    permanent_failures.txt   # Videos that can never be downloaded
```

All video files are saved as `.mp4` in a flat directory (no subdirectories per video).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| All proxies show as DEAD | NordVPN may have temporarily throttled your credentials. Wait 5-10 minutes and try again. |
| "Sign in to confirm you're not a bot" | The proxy IP got flagged by YouTube. The pipeline retries with different proxies automatically. If persistent, reduce `--workers`. |
| "Requested format is not available" | The video only has storyboard images, no real video streams. This is classified as a permanent failure and skipped on re-runs. |
| SOCKS errors during download | Too many concurrent connections. The pipeline has per-proxy semaphores (max 2 concurrent per proxy) and retries with backoff. |
| Cookies causing "format not available" | The pipeline avoids cookies by default for this reason. Cookies are only used as a last resort for age-restricted content. |
