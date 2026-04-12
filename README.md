# PGCasinoWatcher

Community fight recorder for **Project Gorgon's Red Wing Casino - Kuzavek Arena**.

Tails your Project Gorgon VIP chat logs, detects arena fight results from NPC chatter, and submits them to a community intake endpoint for a shared fight log.


## Requirements

- Project Gorgon **VIP** (required for chat logging)
- Chat logging enabled in-game: Settings > VIP > Enable Chat Logging
- Python 3.10+ (if running from source)

## Quick start

Most users should just grab a release:

1. Download the latest release zip and extract it
2. Edit `config.json` if you need to (the release ships with a working community `intake_url`)
3. Double-click `CasinoWatcher.exe`

See [`public/README.md`](public/README.md) for full details, including running from source.



## License

Community tool for Project Gorgon players. Not affiliated with Elder Game, LLC.
