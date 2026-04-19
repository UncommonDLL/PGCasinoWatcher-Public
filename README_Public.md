# CasinoWatcher Public

Fight recorder for **Project Gorgon's Kuzavek Arena**.

Watches game chat logs in real time, detects arena fight results from NPC chatter, normalizes fighter names, deduplicates events, and submits them to a community fight log.

## Requirements

> **Project Gorgon VIP is required.**
>
> CasinoWatcher reads VIP chat logs to detect fight results.
> Without VIP and chat logging enabled, there are no logs to read.
>
> Enable chat logging in-game: **Settings > VIP > Enable Chat Logging**

## What it does

- Auto-detects your Project Gorgon `ChatLogs` directory
- Tails `Chat-*.log` files in real time
- Detects fight introductions and outcomes from Kuzavek NPC patterns
- Normalizes fighter names (handles creative NPC spellings)
- Generates stable dedupe keys to prevent duplicate submissions
- Submits results to a public intake endpoint via HTTPS
- Queues and retries failed submissions automatically

## What it does NOT do

- No credentials or service accounts required
- No direct access to any raw data
- No private data collection

## Quick start (recommended)

1. **Download the latest release** — grab the zip from the Releases page and extract it anywhere
2. **Edit `config.json` if needed** — You usually don't need to change anything; optionally set `contributor_name` for attribution or insert your own `intake_url`.
3. **Double-click `CasinoWatcher.exe`**

That's it. The app auto-detects your ChatLogs folder. If detection fails (e.g., non-standard install), it will walk you through choosing a folder interactively.

### Running from source

1. Install Python 3.10+ from [python.org](https://python.org)
2. Copy `public/config.example.json` to `public/config.json` and optionally edit `intake_url` or `contributor_name`
3. Run: `python public/src/casino_watcher_public.py`

`--config` is optional — by default the app reads `config.json` next to the executable (when frozen) or `public/config.json` (when running from source).

### Dry run mode

Test without submitting to the intake endpoint: python src/casino_watcher_public.py --dry-run

## Config reference

| Field | Default | Description |
|-------|---------|-------------|
| `chatlog_dir` | `""` (auto-detect) | Optional override path to ChatLogs directory |
| `intake_url` | (required) | HTTPS endpoint for fight submissions |
| `state_file` | `casino_watcher_state.json` | Local state persistence |
| `log_file` | `casino_watcher.log` | Local log file |
| `poll_seconds` | `0.75` | How often to check for new log lines |
| `start_mode` | `end` | `end` = live tail, `beginning` = replay |
| `contributor_name` | `""` | Optional name for attribution |

## ChatLogs location

Default on Windows (auto-detected):
%USERPROFILE%\AppData\LocalLow\Elder Game\Project Gorgon\ChatLogs


You only need to set `chatlog_dir` in config.json if:
- Project Gorgon is installed in a non-standard location
- You want to point at a specific folder explicitly

## Fighters

The 7 canonical arena fighters:

- **Corrrak** (three r's) - also matches: Corrak, Corrack, Carrack, etc.
- **Dura**
- **Gloz**
- **Leo**
- **Otis**
- **Ushug**
- **Vizlark**

## Troubleshooting

- **"No Chat-*.log files found"**: Enable VIP chat logging in-game (Settings > VIP > Enable Chat Logging) and play for a moment
- **"CHATLOG SOURCE NOT FOUND"**: You need Project Gorgon VIP — the app will guide you through recovery options
- **Submission failures**: Check internet; failed submissions are queued and retried automatically
- **Duplicate fights**: The dedupe system prevents double-counting; safe to restart anytime

## License

Community tool for Project Gorgon players. Not affiliated with Elder Game, LLC.
