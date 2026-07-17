# AGENTS.md

Guidance for AI agents and contributors working on **cinnamon**.

## What this is

`cinnamon` is a cross-platform CLI (Python) to search TV shows / movies / anime and
play streaming sources in mpv or VLC. It needs **no API key for anime** (AniList +
allanime GraphQL). TMDB (TV/movie metadata) requires a free key set via
`cinnamon config`.

Entry point: `cinnamon.cli:cli` (Click). Run with `cinnamon <command> --help`.

## Project layout

- `cinnamon/cli.py` — Click commands, interactive menus, orchestration.
- `cinnamon/scrapers/` — source adapters.
  - `anime.py` — AniList + allanime (no key); decrypts AES-256-CTR with key `SHA256("Xot36i3lK3:v1")`.
  - `webstream.py` — vixsrc.to + vidlink.pro HLS (append `?lang=en` for English audio).
  - `vidsrc.py`, `torrentio.py` — optional scrapers (movies + TV).
  - `__init__.py` — `_BUILTIN_SCRAPERS = [WebStreamScraper, AnimeScraper]`, optional scrapers, `install_optional()`.
- `cinnamon/player.py` — player launch (mpv/vlc), Termux Android intent handling, download.
- `cinnamon/tmdb.py`, `cinnamon/anilist.py` — metadata clients.
- `cinnamon/history.py`, `cinnamon/downloads.py` — local trackers.
- `tests/` — **manual HTTP-probe scripts** (`test_directstream*.py`), NOT pytest unit tests.
  They print results; run them directly with `python tests/test_directstream.py`.

## Build / install

```bash
pip install -e .                      # editable install
pip install -e ".[scrapers]"          # + playwright for optional scrapers
```

Release install URL pattern:
`https://github.com/pizza-droid/cinnamon/archive/refs/tags/v<version>.tar.gz`

## Versioning & releases

- Single source of truth: `pyproject.toml` `version` AND `cinnamon/__init__.py` `__version__` (keep in sync).
- Tag releases as `vX.Y.Z` (lightweight tags). `_latest_version()` reads the GitHub Tags API
  (`/repos/pizza-droid/cinnamon/tags`), NOT the Releases API (stuck at old versions).
- **Only bump the version when there is a real, publish-worthy change** (new feature, bug fix, behavior
  change). Do NOT bump for trivial doc edits, README wording, or comment changes — those do not need a
  new release or tag. When you do bump, update both version fields, `git commit`, `git tag vX.Y.Z`,
  `git push` + `git push origin vX.Y.Z`, and update the version badge/URL in `README.md` to match.

## Code style

- Standard library + the pinned deps only. Do NOT add new dependencies without updating `pyproject.toml`.
- Follow PEP 8. No external linter configured in this repo — keep imports tidy and consistent with neighbors.
- Lazy-import heavy/optional deps inside the functions that use them (e.g. `pycryptodome` in `anime.py`,
  `playwright` in optional scrapers) so the base install stays light.
- No docstrings required, but keep functions small and named clearly.

## Key invariants / gotchas

- **Anime** routes through allanime's `availableEpisodesDetail` — only actually-available episodes are offered.
  `Frieren` on allanime is E1–E6 only; vixsrc 404s for higher eps. Do not assume full season availability.
- **allanime decryption**: `_decrypt_tobeparsed` returns `{'episode': None}` for missing eps → must raise
  `ScraperNoStreamError`, never let an `AttributeError` escape (fixed in 0.2.13).
- **mp4upload** direct `.mp4` links are hotlink-protected: 403 without `Referer: https://mp4upload.com/`,
  200 with it (verified). On **Termux**, players are launched via `am start` (Android apps) which cannot
  set a Referer, so `player.py` starts a local proxy (`_termux_proxy_url`) that injects the Referer/UA and
  hands the player a `http://127.0.0.1:<port>/video.mp4` URL. Desktop players get the referer via
  `--http-header-fields=Referer:` (mpv) / `--http-referrer=` (vlc).
- **vixsrc / vidlink**: always append `lang=en` (and `h=1`) so audio isn't default-Italian.
- **Scraper fallback**: when an auto-detected scraper fails, `_resolve_and_play` tries other builtin scrapers
  (webstream). An explicit `--scraper` disables fallback.
- **Resume prompt** uses `Prompt.ask` with default `"y"` (not `Confirm.ask`) to avoid loops/aborts (fixed 0.2.12).
- **Termux** player components: mpv `is.xyz.mpv/.MPVActivity`, vlc
  `org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity`. `_termux_ensure_mpv_conf()` writes
  `~/.config/mpv/mpv.conf` with `alang=eng / slang=eng / sub-auto=all`.

## Commands (high level)

- `cinnamon <query>` / `search` — combined TV+movie search; auto-detects anime → allanime flow.
- `cinnamon anime <name>` — allanime sourced anime.
- `cinnamon watch -t movie --id <tmdb_id>` — movie playback (webstream/vidsrc/torrentio).
- `cinnamon config` — set TMDB key, player preference.
- `cinnamon update` — self-update from the latest git tag.
- `cinnamon tui` was removed; do not reinstate.

## Testing

There is no automated test suite. Before bumping a version:
1. `pip install -e .` succeeds.
2. `python -c "import cinnamon.cli, cinnamon.player, cinnamon.scrapers"` imports cleanly.
3. Run relevant `tests/test_directstream*.py` to sanity-check source endpoints (network-dependent).
4. Manually verify a known anime (e.g. `cinnamon frieren`) and a movie resolve + play.
