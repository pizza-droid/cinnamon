# cinnamon

> Search TV shows via TMDB, scrape streaming links from multiple sources, and play them in mpv or VLC — all from the terminal.

[![Version](https://img.shields.io/badge/version-0.1.0-blue)](#)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](#)

![demo](https://img.shields.io/badge/demo-terminal_gif-8A2BE2)

---

## Features

| | |
|---|---|
| **TMDB search** | Search TV shows by name, browse seasons and episodes interactively |
| **2 built-in scrapers** + optional plugins | webstream, anime built-in; vidsrc, torrentio installable |
| **Auto anime detection** | Japanese animation automatically uses the anime scraper |
| **mpv / VLC** | Auto-detects installed player, plays HLS and direct MP4 streams |
| **Download** | Save episodes via yt-dlp with a progress bar |
| **Download tracker** | Resume interrupted downloads, list all tracked downloads |
| **Post-play menu** | After an episode ends, pick next, prev, replay, change quality, or quit |
| **Configurable** | Default scraper, player, theme — all via `cinnamon config` or the setup wizard |
| **TUI** | Full-screen terminal UI powered by Textual |
| **Torrent support** | WebTorrent streaming via Node.js sidecar |

---

## Quick start

### Install

```bash
pip install cinnamon
```

Requires Python 3.10+ and one of [mpv](https://mpv.io) or [VLC](https://videolan.org).

Optional but recommended:

```bash
scoop install yt-dlp          # HLS downloads
npm install                   # WebTorrent support (in project root)
playwright install chromium   # vidsrc scraper
```

### Setup

```bash
cinnamon setup
```

The wizard will ask for a TMDB API key ([sign up free](https://www.themoviedb.org/signup)), your preferred scraper, player, and color theme.

### Watch a show

```bash
cinnamon search "Breaking Bad"
```

Select a show, pick an episode, and it plays. Anime is detected automatically:

```bash
cinnamon search "Chainsaw Man"
```

Pass flags to skip the interactive picker:

```bash
cinnamon watch --id 114410 --season 1 --episode 1
```

---

## Commands

| Command | Description |
|---|---|
| `cinnamon search <query>` | Search, pick a show, select episode, play |
| `cinnamon watch [--id N] [-s S] [-e E]` | Browse episodes interactively |
| `cinnamon play-url <url>` | Play a direct m3u8/mp4 URL |
| `cinnamon download list` | Show all tracked downloads |
| `cinnamon resume` | Resume an interrupted download |
| `cinnamon scrapers` | List available scraper plugins |
| `cinnamon config show` | View current configuration |
| `cinnamon tui` | Launch the full-screen terminal UI |
| `cinnamon setup` | Run the setup wizard |

### Global options

| Flag | Description |
|---|---|
| `--scraper <name>` | Override the default scraper |
| `--player <vlc\|mpv\|auto>` | Override the default player |
| `-q, --quality <480p\|720p\|1080p\|best\|worst>` | Request a specific quality |
| `-d, --download` | Download instead of streaming |
| `--info-only` | Print the stream URL and exit |
| `-s, --season <N>` | Season number |
| `-e, --episode <N>` | Episode number or range (e.g. `1` or `1-10`) |

---

## Scrapers

| Name | Type | Description |
|---|---|---|
| `webstream` | built-in | HTTP streams from vixsrc.to and vidlink.pro |
| `anime` | built-in | Anime from allanime.day via mp4upload |

### Optional

These scrapers aren't loaded by default (they need extra dependencies). Install with `cinnamon install <name>`:

| Name | Description | Needs |
|---|---|---|
| `vidsrc` | Streams from vidsrc domains via Playwright | `playwright install chromium` |
| `torrentio` | Torrent streams via Torrentio (1337x, TPB, RARBG) | `npm install` for WebTorrent playback |

```bash
cinnamon install vidsrc
cinnamon install torrentio
```

Set the default:

```bash
cinnamon config default-scraper webstream
```

### Writing your own

Drop a `.py` file in `~/.config/cinnamon/scrapers/` with a class that inherits `BaseScraper` and implements `search()` and `resolve()`. It shows up automatically.

---

## Configuration

Config lives at `~/.config/cinnamon/config.json`.

| Key | Default | Description |
|---|---|---|
| `tmdb_api_key` | — | Your TMDB API key |
| `default_scraper` | `webstream` | Scraper to use when none is specified |
| `default_player` | `auto` | Player priority: `auto` → mpv → VLC |
| `theme` | `cinnamon` | Color theme: `cinnamon`, `ocean`, `mono` |

Manage it via commands or by editing the file directly:

```bash
cinnamon config default-player mpv
cinnamon config set-api-key YOUR_KEY
```

---

## Supported sources

The `webstream` scraper works by scraping public streaming aggregator sites:

1. **vixsrc.to** — TV show API → embed page → token extraction → HLS master playlist
2. **vidlink.pro** — encrypted ID API → stream API → direct m3u8 (fallback)

The `anime` scraper uses the **allanime.day** GraphQL API (no Cloudflare required) and extracts direct MP4 URLs from mp4upload embed pages. Other providers (Ok.ru, Streamlare, Streamsb) are listed by the API but their embed pages use anti-bot JavaScript and are not currently extractable.

---

## Project structure

```
cinnamon/
├── cinnamon/
│   ├── cli.py               # Click CLI, all commands
│   ├── config.py             # JSON config management
│   ├── tmdb.py               # TMDB API v3 client
│   ├── player.py             # mpv / VLC / yt-dlp launchers
│   ├── download.py           # Download tracker (JSON DB)
│   ├── errors.py             # Error hierarchy
│   ├── tui.py                # Textual full-screen TUI
│   └── scrapers/
│       ├── __init__.py       # Scraper registry + discovery
│       ├── base.py           # BaseScraper + ScraperResult
│       ├── webstream.py      # vixsrc.to / vidlink.pro
│       ├── anime.py          # allanime.day / mp4upload
│       ├── vidsrc.py         # Playwright-based (install via cinnamon install)
│       └── torrentio.py      # Torrentio API (install via cinnamon install)
├── pyproject.toml
└── package.json              # WebTorrent bridge
```

---

## Development

```bash
git clone https://github.com/your-username/cinnamon
cd cinnamon
pip install -e .
npm install          # WebTorrent dependencies
```

Run tests:

```bash
pytest               # if available
```

---

## Contributing

1. Fork the repo and create a branch: `git checkout -b feature/my-feature`
2. Make your changes
3. Run the linter if configured
4. Open a pull request with a clear description

---

## License

MIT — see [LICENSE](LICENSE) for details.
