# cinnamon

> Watch TV shows and anime from your terminal. Search, pick an episode, and it plays in mpv or VLC.

[![Version](https://img.shields.io/badge/version-0.2.8-blue)](#)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](#)
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20macos%20%7C%20linux%20%7C%20termux-lightgrey)](#)

## Quick start

You'll need **Python 3.10+** and either [mpv](https://mpv.io) or [VLC](https://videolan.org).

### Install

```bash
pip install https://github.com/pizza-droid/cinnamon/archive/refs/tags/v0.2.8.tar.gz
cinnamon setup
```

The setup wizard asks for a TMDB API key ([free account](https://www.themoviedb.org/signup)), your preferred player, and a color theme.

### Get a player

| Platform | mpv | VLC |
|---|---|---|
| **Windows** | `scoop install mpv` or download from [mpv.io](https://mpv.io) | [videolan.org](https://videolan.org) |
| **macOS** | `brew install mpv` | `brew install --cask vlc` |
| **Linux** | `apt install mpv` (Debian/Ubuntu) | `apt install vlc` |
| **Termux** | `pkg install mpv` | `pkg install vlc` |

### Watch a show

```bash
cinnamon search "Breaking Bad"
```

Pick a show, pick an episode, and it plays. Anime is detected automatically:

```bash
cinnamon search "Chainsaw Man"
```

### Download episodes

Needs [yt-dlp](https://github.com/yt-dlp/yt-dlp):

| Platform | Command |
|---|---|
| Windows | `scoop install yt-dlp` |
| macOS | `brew install yt-dlp` |
| Linux | `pip install yt-dlp` |
| Termux | `pkg install yt-dlp` |

```bash
cinnamon search "Breaking Bad" -d -e 1-5
```

---

## Commands

| If you run this… | …this happens |
|---|---|
| `cinnamon anime <query>` | Search anime via AniList (no API key needed) |
| `cinnamon search <query>` | Find a show, pick an episode, watch it |
| `cinnamon watch --id 123 -s 2 -e 5` | Go straight to S2E5 without menus |
| `cinnamon play-url <url>` | Play any m3u8/mp4 link |
| `cinnamon resume` | Continue an interrupted download |
| `cinnamon history` | Show watch history and resume from last episode |
| `cinnamon history --clear` | Clear all watch history |
| `cinnamon scrapers` | See available streaming sources |
| `cinnamon install <name>` | Add an optional scraper (vidsrc, torrentio) |
| `cinnamon update` | Check for and install the latest version |
| `cinnamon config show` | View your settings |

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
| `vidsrc` | `pip install "cinnamon[scrapers]"` then `playwright install chromium` |
| `torrentio` | `npm install` (torrent playback) |

```bash
cinnamon install torrentio
cinnamon config default-scraper torrentio
```

---

## Configuration

Settings are stored in `~/.config/cinnamon/config.json` (Linux/macOS/Termux) or `%APPDATA%/cinnamon/config.json` (Windows). Change them anytime:

```bash
cinnamon config default-player mpv
cinnamon config default-scraper webstream
cinnamon config set-api-key YOUR_KEY
```

---

## Notes

This project is mostly vibe coded and my lazy ass didnt even write more than a 1000 lines.
feel free to give me feedback so we can improve this project and make it as good as possible
