# TalkVid YouTube Clip Downloader

Fast parallel YouTube clip downloader with proxy rotation, cookie management, and Slack progress notifications.

Downloads video clips specified in a JSON file using yt-dlp, with:
- **Round-robin proxy rotation** across 50+ SOCKS5 proxy IPs (Torguard recommended, NordVPN optional)
- **Per-proxy rate limiting** (semaphores) to avoid proxy throttling
- **Automatic proxy health checks** every 5 minutes (dead proxies are skipped, recovered ones re-added)
- **Smart retry with different proxies** — tries 5 unique proxy IPs per URL before falling back
- **Direct-IP fallback** — last resort when all proxies fail for a URL
- **Cookie pool support** for age-restricted content (used only as last resort)
- **Resume support** — re-run the same command and already-downloaded clips are skipped
- **Slack webhook notifications** with download progress, failure breakdowns by reason, and raw error messages
- **Per-run log files** — each run gets its own timestamped log directory
- **Video-only flat output** — all `.mp4` files in one directory

## Files

| File | Description |
|------|-------------|
| `download_clips.py` | Main download pipeline |
| `socks_to_http_proxy.py` | HTTP-to-SOCKS5 proxy bridge (one per proxy IP) |
| `start_torguard_all.sh` | **Recommended**: Start all 50 Torguard proxy bridges |
| `start_torguard_proxies.sh` | Start 10 Torguard proxy bridges (lighter) |
| `start_proxies.sh` | Start 9 NordVPN proxy bridges (optional) |
| `cookie_refresher.py` | Export & upload cookies from a single Chrome profile |
| `cookie_refresher_v2.py` | **Recommended**: Export & upload cookies from multiple Chrome profiles at once |
| `ffmpeg_wrapper/ffmpeg` | Wrapper that injects proxy settings into ffmpeg calls |
| `cookies_pool/` | Directory for cookie files (one per YouTube account) |

## Prerequisites

```bash
pip install yt-dlp PySocks rich
```

You also need:
- **ffmpeg** installed and available in PATH
- **Node.js** installed (used by yt-dlp to solve YouTube challenges)
- A **Torguard** subscription ($5.95/month) — provides 50+ SOCKS5 proxy IPs
- (Optional) A **NordVPN** subscription — provides 9 additional proxy IPs, but these are broadly flagged by YouTube
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

### 2. Start Torguard proxy bridges (recommended)

Torguard provides **50 SOCKS5 proxy IPs** across Canada and UK that are not flagged by YouTube's bot detection. This is the recommended proxy provider.

> **Why Torguard over NordVPN?** NordVPN datacenter IPs are broadly flagged by YouTube — almost every request gets "Sign in to confirm you're not a bot". Torguard IPs are clean: in testing, **98.8% of downloads succeeded via Torguard proxy** with zero bot detection errors.

**Sign up:** [torguard.net/anonymous-bittorrent-proxy](https://torguard.net/anonymous-bittorrent-proxy/) ($5.95/month proxy plan)

**Set up proxy credentials** (different from your account login):
1. Log into torguard.net
2. Go to **My Account** > **Change Passwords** (managecredentials.php)
3. Set a **Proxy/SOCKS username** and **password**

**Start all 50 bridges:**
```bash
./start_torguard_all.sh 'YOUR_TORGUARD_USER:YOUR_TORGUARD_PASS'
```

This starts 50 proxy bridges on ports 9080-9129:

| Region | IPs | Ports |
|--------|-----|-------|
| Canada - Montreal (89.47.234.x) | 10 IPs | 9080-9089 |
| Canada - Montreal (86.106.90.x) | 5 IPs | 9090-9094 |
| Canada - Montreal (146.70.27.x) | 10 IPs | 9095-9104 |
| Canada - Montreal (176.113.74.x) | 15 IPs | 9105-9119 |
| UK - London (146.70.95.x) | 10 IPs | 9120-9129 |

**Alternatively, start only 10 bridges** (lighter, for testing):
```bash
./start_torguard_proxies.sh 'YOUR_TORGUARD_USER:YOUR_TORGUARD_PASS'
```

### 2b. Start NordVPN proxy bridges (optional)

NordVPN provides 9 additional proxy IPs. They are mostly bot-detected by YouTube, but the pipeline will retry with Torguard IPs automatically. Adding NordVPN increases your total IP pool.

```bash
./start_proxies.sh 'YOUR_NORDVPN_USER:YOUR_NORDVPN_PASS'
```

This starts 9 bridges on ports 8080-8088 across US and EU regions.

#### How to get NordVPN SOCKS5 credentials

The credentials used here are **not** your NordVPN account email/password. They are separate "service credentials" for manual connections.

1. Log in to [my.nordaccount.com](https://my.nordaccount.com/)
2. Go to **Services** > **NordVPN**
3. Scroll down to **Manual Setup**
4. Select the **OpenVPN / IKEv2** tab (or **Service credentials** depending on the UI version)
5. You will see a **Username** (a long random string) and a **Password** — these are your SOCKS5 credentials
6. Use them as `--proxy-creds 'USERNAME:PASSWORD'` in the download command

### 3. Set up cookies (optional)

Cookies are used as a **last resort** when YouTube requires authentication (e.g., age-restricted videos). The pipeline tries without cookies first because cookie files can cause YouTube to restrict available video formats if the associated Google account has been flagged for automated access.

> **Note:** If your Google accounts have been used for bulk downloading with yt-dlp before, they are likely flagged by YouTube and the cookies will cause "format not available" errors. Fresh accounts that have never been used for automated downloads are needed for cookies to work.

#### Keeping cookies fresh

YouTube cookies expire frequently. Run the cookie refresher **on your local machine** (where you have a browser with YouTube logged in) to periodically export fresh cookies and upload them to the download server.

**cookie_refresher_v2.py** (recommended) — handles all profiles in a single process with retry logic:

1. Edit the `PROFILES` list in `cookie_refresher_v2.py` to match your Chrome profiles:
   ```python
   PROFILES = [
       "Default",
       "Profile 1",
       "Profile 2",
       # Add more...
   ]
   ```
   Check profile names in `chrome://version/` (the Profile Path shows the directory name).

2. Run it:
   ```bash
   python cookie_refresher_v2.py \
       --remote-host user@your-server \
       --remote-dir /path/to/cookies_pool \
       --interval 25
   ```
   This exports cookies from all profiles every 25 minutes and uploads each as a separate file (e.g., `live_cookies_chrome_Default.txt`, `live_cookies_chrome_Profile_1.txt`).

**cookie_refresher.py** — single-profile alternative (run one instance per profile):
```bash
python cookie_refresher.py --remote-host user@server --remote-path /path/to/cookies_pool/account1.txt --browser chrome
python cookie_refresher.py --remote-host user@server --remote-path /path/to/cookies_pool/account2.txt --browser "chrome:Profile 2"
```

**Important:** Each Chrome profile must be signed in to a **different Google account**. Multiple profiles on the same account won't help — YouTube flags per account, not per profile.

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

**Torguard only** (recommended — 50 proxy IPs, best results):
```bash
# Terminal 1: Start bridges
./start_torguard_all.sh 'YOUR_TORGUARD_USER:YOUR_TORGUARD_PASS'

# Terminal 2: Run pipeline
python download_clips.py \
    --input ../TalkVid_Data/data/filtered_video_clips.json \
    --output ./videos_output \
    --torguard-list all \
    --torguard-creds 'YOUR_TORGUARD_USER:YOUR_TORGUARD_PASS' \
    --workers 36 \
    --slack-webhook "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
```

**Torguard + NordVPN combined** (59 proxy IPs):
```bash
# Terminal 1: Start all bridges
./start_torguard_all.sh 'YOUR_TORGUARD_USER:YOUR_TORGUARD_PASS' &
./start_proxies.sh 'YOUR_NORDVPN_USER:YOUR_NORDVPN_PASS' &

# Terminal 2: Run pipeline
python download_clips.py \
    --input ../TalkVid_Data/data/filtered_video_clips.json \
    --output ./videos_output \
    --torguard-list all \
    --torguard-creds 'YOUR_TORGUARD_USER:YOUR_TORGUARD_PASS' \
    --proxy-list new-york,los-angeles,chicago,dallas,atlanta,san-francisco,phoenix,amsterdam,stockholm \
    --proxy-creds 'YOUR_NORDVPN_USER:YOUR_NORDVPN_PASS' \
    --workers 36 \
    --slack-webhook "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
```

### All Options

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | (required) | Path to input JSON file |
| `--output` | (required) | Output directory for downloaded videos |
| `--workers` | 18 | Number of parallel download workers |
| `--torguard-list` | None | Comma-separated Torguard proxy names or `all` |
| `--torguard-creds` | None | Torguard SOCKS5 credentials (`user:pass`) |
| `--proxy-list` | None | Comma-separated NordVPN region names |
| `--proxy-creds` | None | NordVPN SOCKS5 credentials (`user:pass`) |
| `--proxy` | None | Single proxy URL |
| `--cookies-dir` | None | Directory with cookie `.txt` files |
| `--cookies` | None | Path to a single cookie file |
| `--slack-webhook` | None | Slack webhook URL for notifications |
| `--slack-interval` | 10 | Send Slack update every N URLs processed |
| `--limit` | None | Max segments to process (for testing) |
| `--browser` | None | Extract cookies from browser directly |
| `--extractor-args` | None | Pass through to yt-dlp `--extractor-args` |

## How the Pipeline Works

### Download flow per URL

Each URL goes through this retry sequence:

```
Attempt 1-5:  5 different proxy IPs (round-robin, skips already-tried proxies)
              No backoff between bot-detection retries (different IP solves it)
              Exponential backoff only for socks/timeout errors
Fallback 1:   Proxy + cookie (for bot-detected or age-restricted content)
Fallback 2:   Direct IP, no cookies (bypasses proxy-IP bot detection)
Fallback 3:   Direct IP + cookie (last resort)
```

Permanent errors (video unavailable, account terminated, no video streams) stop retries immediately at any step.

### Proxy management

- **Startup health check**: all proxies are tested via their HTTP bridges; dead ones are excluded
- **Background recheck**: every 5 minutes, all proxies are retested. Dead proxies are removed and recovered proxies are re-added. Changes are reported via Slack.
- **Per-proxy semaphore**: max 2 concurrent downloads per proxy to avoid throttling
- **Unique proxy selection**: each retry attempt picks a proxy that hasn't been tried yet for that URL

### Cookie strategy

Cookies are **avoided by default** because they can cause YouTube to restrict video format availability (returning only storyboard images instead of real video). This happens when the Google account has been flagged for automated access. Cookies are only used as a fallback after all proxy-only retries have failed.

### Resume & interrupted downloads

The pipeline is fully re-runnable. Just run the same command again:
- **Completed clips** are skipped (checked via `json_logs/`)
- **Permanently unavailable videos** are skipped (checked via cumulative `logs/permanent_failures.txt`)
- **Partially downloaded files** (`.part`) from interrupted runs are resumed automatically — yt-dlp picks up where it left off instead of starting over
- **Stale `.part` files** older than 24 hours are cleaned up at startup (truly abandoned downloads)
- **Transient failures** (socks error, rate limit, etc.) are retried

### Slack Notifications

The pipeline sends Slack messages at these points:
- **Start** — URL count, worker/proxy configuration, resume count
- **Every N URLs** (default 10) — progress with per-batch and cumulative stats
- **Proxy health changes** — when the background recheck detects proxies dying or recovering
- **End** — final summary with totals

Each progress update includes:
- **Cumulative totals** — total clips downloaded, skipped, and failed
- **Download methods** — how clips were downloaded (`proxy`, `direct`, `proxy+cookie`, `direct+cookie`)
- **This batch** — clips downloaded and failures since the last Slack update
- **Failure breakdown** — categorized reasons (e.g., "video unavailable", "private video", "socks error")
- **Uncategorized errors** — raw error messages with video IDs for diagnosis

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
  Failed: video unavailable: 5

Total failures by reason:
  • video unavailable: 7
  • private video: 4
  Total failed clips: 11
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

## Troubleshooting

| Problem | Solution |
|---------|----------|
| All proxies show as DEAD | The proxy provider may have temporarily throttled your credentials. Wait 5-10 minutes and try again. |
| "The page needs to be reloaded" | YouTube bot detection on the proxy IP. The pipeline retries with up to 5 different proxy IPs, then falls back to proxy+cookie and direct IP. Torguard IPs rarely trigger this. |
| "Sign in to confirm you're not a bot" | Same as above — proxy IP flagged. NordVPN IPs are broadly flagged; Torguard IPs are much cleaner. |
| "Requested format is not available" | The video only has storyboard images, no real video streams. Classified as permanent failure, skipped on re-runs. |
| SOCKS errors during download | Too many concurrent connections. The pipeline has per-proxy semaphores (max 2 concurrent) and retries with exponential backoff. |
| Cookies causing "format not available" | The Google account is flagged for automated access. The pipeline avoids cookies by default. Use fresh accounts if cookies are needed. |
| "SOCKS5 authentication failed" | Proxy credentials may have been rotated. Check your Torguard credentials at managecredentials.php or NordVPN credentials at my.nordaccount.com. |
| "Address already in use" when starting bridges | Previous bridge processes are still running. Kill them with `pkill -9 -f socks_to_http_proxy` then try again. |

## Performance

Tested with 2,000 clips, 50 Torguard proxies, 36 workers:

| Metric | Value |
|--------|-------|
| Success rate | 98.9% (1,977/2,000) |
| Speed | 34.8 clips/min |
| Via proxy | 98.8% of downloads |
| Via direct IP | 1.2% of downloads |
| Socks errors | 0 |
| Bot detection errors | 0 |
| All failures | Genuinely unavailable videos |
