# Cinnamon | Beta

Watch TV shows, movies, and anime from your terminal. Search, pick a title, and it plays in mpv or VLC.

[![version](https://img.shields.io/pypi/v/cinnamon-cli)](https://pypi.org/project/cinnamon-cli/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](#)
[![License](https://img.shields.io/badge/license-CC%20BY--NC%204.0-green)](#)
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20macos%20%7C%20linux%20%7C%20termux-lightgrey)](#)

## Quick start

You'll need **Python 3.10+** and either [mpv](https://mpv.io) or [VLC](https://videolan.org).

### Install

```bash
pip install cinnamon-cli
cinnamon setup
```

> The setup wizard asks for a TMDB API key ([Create a free account here](https://www.themoviedb.org/signup)), the api key is used for show and movie information. If you skip it, it will use an **experimental** 2embed search (no key needed), it works but is less reliable.



### Get a player
> Please note that MacOS version has not been tested since we dont have access to a mac

| Platform | mpv | VLC |
|---|---|---|
| **Windows** | `scoop install mpv` or download from [mpv.io](https://mpv.io) | [videolan.org](https://videolan.org) |
| **macOS** | `brew install mpv` | `brew install --cask vlc` |
| **Linux** | `apt install mpv` (Debian/Ubuntu) | `apt install vlc` |
| **Termux** | `pkg install mpv` | `pkg install vlc` |

### Watch a show or movie

```bash
cinnamon search "Breaking Bad"
cinnamon search "Inception"
```

For Anime you can run:

```bash
cinnamon anime "Chainsaw Man"
```

By default you'll be asked whether to watch sub or dub. Skip the prompt with
`-sub` / `-dub`:

```bash
cinnamon anime "Chainsaw Man" --sub
cinnamon anime "Frieren" --dub
```


you can also run it like this:

```bash
cinnamon Inception
cinnamon Breaking bad
cinnamon chainsaw man # Not reccomended to search an anime like this
```

### Download episodes

Downloading needs [yt-dlp](https://github.com/yt-dlp/yt-dlp).


```bash
pip install yt-dlp
```

Now you can run:

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
| `cinnamon history` | Show watch history |
| `cinnamon history <query>` | Show episodes played for a show and continue from next |
| `cinnamon history clear` | Clear all watch history |
| `cinnamon history toggle [on|off]` | Enable or disable history tracking |
| `cinnamon config history show` | Show whether history tracking is enabled |
| `cinnamon config history toggle [on/off]` | Enable or disable via config |
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
| `--sub` | Prefer subtitled audio (skips the translation prompt) |
| `--dub` | Prefer dubbed audio (skips the translation prompt) |
| `--info-only` | Just print the stream URL |

---

## Scrapers (streaming sources)

**Built-in (work out of the box):**

| Name | For |
|---|---|
| `webstream` | TV shows & movies from vixsrc.to and vidlink.pro (HLS) |
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

**anime movies do not work right now**, we're working on it, but due to the nature of the scrapers we use, its currently not possible to watch anime movies from cinnamon, this will be fixed soon.

This project is mostly vibe coded and our lazy ass didnt even write more than 300 lines of code.
feel free to give us feedback so we can improve this project and make it as good as possible.

inspired by [ani-cli](https://github.com/pystardust/ani-cli)
