# cinnamon

> Watch TV shows and anime from your terminal. Search, pick an episode, and it plays in mpv or VLC.

[![Version](https://img.shields.io/badge/version-0.1.0-blue)](#)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](#)

## Quick start

You'll need **Python 3.10+** and either [mpv](https://mpv.io) or [VLC](https://videolan.org).

```bash
pip install cinnamon
cinnamon setup
```

The setup wizard asks for a TMDB API key ([free account](https://www.themoviedb.org/signup)), your preferred player, and a color theme.

### Watch a show

```bash
cinnamon search "Breaking Bad"
```

Pick a show, pick an episode, and it plays. Anime is detected automatically:

```bash
cinnamon search "Chainsaw Man"
```

### Download episodes

```bash
cinnamon search "Breaking Bad" -d -e 1-5
```

Downloads seasons 1–5. Needs [yt-dlp](https://github.com/yt-dlp/yt-dlp) (`scoop install yt-dlp`).

---

## Commands

| If you run this… | …this happens |
|---|---|
| `cinnamon search <query>` | Find a show, pick an episode, watch it |
| `cinnamon watch --id 123 -s 2 -e 5` | Go straight to S2E5 without menus |
| `cinnamon play-url <url>` | Play any m3u8/mp4 link |
| `cinnamon resume` | Continue an interrupted download |
| `cinnamon scrapers` | See available streaming sources |
| `cinnamon install <name>` | Add an optional scraper (vidsrc, torrentio) |
| `cinnamon config show` | View your settings |
| `cinnamon tui` | Full-screen mode |

### Common flags

| Flag | What it does |
|---|---|
| `-s <N>` | Season number |
| `-e <N>` or `-e <start-end>` | Episode or range (e.g. `-e 1-10`) |
| `-d` | Download instead of streaming |
| `--scraper <name>` | Force a specific scraper |
| `--player mpv` or `--player vlc` | Choose player |
| `-q 720p` | Pick quality (480p, 720p, 1080p, best, worst) |
| `--info-only` | Just print the stream URL |

---

## Scrapers (streaming sources)

**Built-in (work out of the box):**

| Name | For |
|---|---|
| `webstream` | TV shows from vidlink.pro |
| `anime` | Anime from allanime.day via mp4upload |

**Optional (install with `cinnamon install <name>`):**

| Name | Needs |
|---|---|
| `vidsrc` | `playwright install chromium` |
| `torrentio` | `npm install` (torrent playback) |

```bash
cinnamon install torrentio
cinnamon config default-scraper torrentio
```

---

## Configuration

Settings are stored in `~/.config/cinnamon/config.json`. Change them anytime:

```bash
cinnamon config default-player mpv
cinnamon config default-scraper webstream
cinnamon config set-api-key YOUR_KEY
```

---

## License

MIT
