import concurrent.futures
import subprocess
import sys
import time
import webbrowser
from functools import wraps

import click
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import (
    get_ensured_dirs,
    get_scraper_config,
    get_theme,
    get_tmdb_api_key,
    load_config,
    save_config,
    set_scraper_config,
    THEMES,
)
from .errors import (
    CinnamonError,
    MissingAPIKey,
    PlayerLaunchError,
    PlayerNotFoundError,
    ScraperError,
    TMDBAuthError,
    TMDBConnectionError,
    TMDBError,
    TMDBNotFoundError,
    TMDBRateLimitError,
)
from .player import download_video, play, ytdlp_install_hint
from .scrapers import get_scraper, list_scrapers
from .tmdb import TMDBClient

console = Console()

RESOLVE_TIMEOUT = 90

_ANIME_GENRE_ID = 16


def _is_anime(show):
    origin = show.get("origin_country") or []
    if "JP" not in origin:
        return False
    if show.get("original_language") == "ja":
        return True
    ids = show.get("genre_ids") or [g["id"] for g in show.get("genres", []) if "id" in g]
    if _ANIME_GENRE_ID in ids:
        return True
    return False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _print_error(title, detail=None):
    t = get_theme()
    if detail:
        console.print(Panel(f"[{t['error']}]{title}[/{t['error']}]\n[{t['dim']}]{detail}[/{t['dim']}]", border_style=t["error"]))
    else:
        console.print(Panel(f"[{t['error']}]{title}[/{t['error']}]", border_style=t["error"]))


def _print_success(title, detail=None):
    t = get_theme()
    if detail:
        console.print(Panel(f"[{t['success']}]{title}[/{t['success']}]\n[{t['dim']}]{detail}[/{t['dim']}]", border_style=t["success"]))
    else:
        console.print(Panel(f"[{t['success']}]{title}[/{t['success']}]", border_style=t["success"]))


def _print_info(title, detail=None):
    t = get_theme()
    if detail:
        console.print(Panel(f"[{t['info']}]{title}[/{t['info']}]\n[{t['dim']}]{detail}[/{t['dim']}]", border_style=t["info"]))
    else:
        console.print(Panel(f"[{t['info']}]{title}[/{t['info']}]", border_style=t["info"]))


# ---------------------------------------------------------------------------
# interactive selection UI
#
# One focus point: the highlighted row (class:highlighted) is bright, every
# other row (class:text) is dimmed grey, and the question line (class:question)
# is the anchor. All pickers route through _select so the look is consistent.
# ---------------------------------------------------------------------------

_POINTER = "❯"

# prompt_toolkit needs hex colors, not rich color names. Map the theme accents
# to hex so the picker's focus color matches the active theme.
_Q_HEX = {
    "orange1": "#ffaf00",
    "deep_sky_blue1": "#00afff",
    "blue": "#0000ff",
    "white": "#ffffff",
    "bright_white": "#ffffff",
    "grey50": "#7f7f7f",
    "grey35": "#595959",
}


def _q_hex(name):
    return _Q_HEX.get(name, "#ffaf00")


def _q_style():
    """questionary Style that makes the focused choice the clear focus point."""
    t = get_theme()
    accent = _q_hex(t.get("accent", "orange1"))
    dim = _q_hex(t.get("dim", "grey50"))
    return questionary.Style(
        [
            ("qmark", f"fg:{accent}"),
            ("question", f"bold fg:{accent}"),
            ("pointer", f"bold fg:{accent}"),
            ("highlighted", f"bold fg:{accent}"),
            ("text", f"fg:{dim}"),
            ("separator", f"fg:{dim}"),
            ("instruction", f"fg:{dim}"),
            ("answer", f"bold fg:{accent}"),
        ]
    )


def _select(message, choices, default=None, **kwargs):
    """questionary.select with cinnamon's focus style applied."""
    kwargs.setdefault("pointer", _POINTER)
    try:
        return questionary.select(
            message, choices=choices, default=default, style=_q_style(), **kwargs
        ).unsafe_ask()
    except Exception:
        return None


def _prompt(message, default=None, password=False):
    """rich Prompt.ask that degrades gracefully when stdin is closed (EOF) or
    not a TTY — returns the default instead of aborting the whole command.

    This is what keeps the CLI from crashing under automation, Termux, or a
    closed pipe (where Prompt.ask raises EOFError and click turns it into a
    hard SystemExit)."""
    try:
        return Prompt.ask(message, default=default, password=password)
    except (EOFError, KeyboardInterrupt):
        return default
    except Exception:
        return default


_UPDATE_CHECK_CACHE = 86400  # 24 hours


_UPDATE_REPO = "pizza-droid/cinnamon"


_UPDATE_CHECK_FALLBACK_DAYS = 7


def _latest_version():
    import requests

    # Primary: GitHub Tags API (includes lightweight tags, not just releases).
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{_UPDATE_REPO}/tags",
            timeout=8,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code == 200:
            tags = resp.json()
            if tags:
                tag = tags[0].get("name", "")
                if tag:
                    return tag[1:] if tag.startswith("v") else tag
    except Exception:
        pass

    # Fallback: parse version from pyproject.toml on the default branch.
    try:
        resp = requests.get(
            f"https://raw.githubusercontent.com/{_UPDATE_REPO}/master/pyproject.toml",
            timeout=8,
        )
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("version = "):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def _check_for_updates():
    try:
        cfg = load_config()
        last_check = cfg.get("_update_check", 0)
        if time.time() - last_check < _UPDATE_CHECK_CACHE:
            return

        latest = _latest_version()
        if not latest:
            # Network failed — don't cache, retry next run.
            return

        current = __version__
        try:
            cur = tuple(map(int, current.split(".")))
            lat = tuple(map(int, latest.split(".")))
        except ValueError:
            cfg["_update_check"] = time.time()
            save_config(cfg)
            return

        if lat <= cur:
            # Up to date: record check so we don't nag for a while.
            cfg["_update_check"] = time.time()
            save_config(cfg)
            return

        # Update available: remind every run (don't cache the timestamp).
        t = get_theme()
        console.print(
            f"  [{t['info']}]Update available:[/] {current} → [bold]{latest}[/]  "
            f"[dim](run[/dim] [cyan]cinnamon update[/cyan][dim])[/dim]"
        )
    except Exception:
        pass


def _get_tmdb():
    try:
        return TMDBClient()
    except MissingAPIKey:
        _print_error(
            "TMDB API key not configured.",
            'Run "cinnamon setup" for a step-by-step guide to get a free key.',
        )
        raise SystemExit(1)


def _handle_tmdb_error(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except TMDBAuthError as e:
            _print_error(str(e))
        except TMDBRateLimitError:
            _print_error("TMDB rate limit reached. Wait a moment and try again.")
        except TMDBConnectionError as e:
            _print_error(str(e))
        except TMDBNotFoundError as e:
            _print_error(str(e))
        except TMDBError as e:
            _print_error(str(e))
        except MissingAPIKey:
            _get_tmdb()

    return wrapper


def _pick_combined(items, message):
    """Picker for mixed TV/movie results; tags each entry with its type."""
    if not items:
        return None
    try:
        choices = []
        for item in items:
            mtype = item.get("_media_type", "tv")
            title = item.get("title") or item.get("name") or "?"
            date = item.get("release_date") or item.get("first_air_date") or ""
            year = (date or "")[:4]
            tag = "Movie" if mtype == "movie" else "TV"
            label = f"{title}  ({year})  [{tag}]"
            choices.append(questionary.Choice(title=label, value=item))
        return _select(message, choices)
    except Exception:
        # Fallback to a numbered table
        table = Table(border_style="dim")
        table.add_column("#", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Year", style="green")
        table.add_column("Type", style="yellow")
        for i, item in enumerate(items, 1):
            mtype = item.get("_media_type", "tv")
            title = item.get("title") or item.get("name") or "?"
            date = item.get("release_date") or item.get("first_air_date") or ""
            table.add_row(str(i), title, (date or "")[:4], "Movie" if mtype == "movie" else "TV")
        console.print(table)
        attempts = 0
        while True:
            try:
                choice = int(_prompt(f"{message} (enter number)", default="1"))
                if 1 <= choice <= len(items):
                    return items[choice - 1]
                console.print(f"[red]Pick a number between 1 and {len(items)}.[/red]")
            except ValueError:
                console.print("[red]Invalid input. Enter a number.[/red]")
            attempts += 1
            if attempts >= 10:
                console.print("[red]Too many invalid attempts.[/red]")
                return None


def _pick_with_arrows(items, title_key, subtitle_key, message):
    if not items:
        return None
    try:
        choices = []
        for item in items:
            if callable(title_key):
                title = str(title_key(item) or "?")
            else:
                title = str(item.get(title_key, "?") or "?")
            subtitle = ""
            if subtitle_key:
                if callable(subtitle_key):
                    subtitle = str(subtitle_key(item) or "")
                else:
                    subtitle = str(item.get(subtitle_key, "") or "")
            label = title if not subtitle else f"{title}  ({subtitle})"
            choices.append(questionary.Choice(title=label, value=item))
        return _select(message, choices)
    except Exception:
        return _pick_numbered(items, title_key, subtitle_key, message)


def _pick_numbered(items, title_key, subtitle_key, message):
    if not items:
        return None
    table = Table(border_style="dim")
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    if subtitle_key:
        table.add_column(subtitle_key.capitalize() if isinstance(subtitle_key, str) else "", style="green")

    for i, item in enumerate(items, 1):
        if callable(title_key):
            title = str(title_key(item) or "?")
        else:
            title = str(item.get(title_key, "?") or "?")
        row = [str(i), title]
        if subtitle_key:
            if callable(subtitle_key):
                row.append(str(subtitle_key(item) or ""))
            else:
                row.append(str(item.get(subtitle_key, "") or ""))
        table.add_row(*row)

    console.print(table)
    attempts = 0
    while True:
        try:
            choice = int(_prompt(f"{message} (enter number)", default="1"))
            if 1 <= choice <= len(items):
                return items[choice - 1]
            console.print(f"[red]Pick a number between 1 and {len(items)}.[/red]")
        except ValueError:
            console.print("[red]Invalid input. Enter a number.[/red]")
        attempts += 1
        if attempts >= 10:
            console.print("[red]Too many invalid attempts.[/red]")
            return None


def _parse_episode(ep_str):
    """Parse episode string. Returns (start, end) or (None, None)."""
    if not ep_str:
        return None, None
    parts = str(ep_str).split("-", 1)
    try:
        start = int(parts[0])
    except ValueError:
        return None, None
    if len(parts) == 2:
        try:
            end = int(parts[1])
        except ValueError:
            return None, None
        if end < start:
            return None, None
        return start, end
    return start, None


def _play_with_menu(show, season_num, ep_start, ep_end, ep_name, scraper, player, quality, info_only, download=False, translation=None):
    """Play episode(s), then show interactive menu until user quits."""

    from .history import set_history as _set_history

    def _save_history(ep):
        _set_history(show.get("name", "?"), season_num, ep, scraper=scraper, translation=translation, quality=quality)

    if ep_end is not None and ep_end > ep_start:
        if not download:
            _print_error("Episode ranges are only supported with --download.")
            return
        from .downloads import create as _track_create
        show_name = show.get("name", "?")
        range_track_id = _track_create({
            "title": show_name,
            "url": "",
            "tv_id": show.get("id", 0),
            "season": season_num,
            "episode": f"{ep_start}-{ep_end}",
            "quality": quality or "",
            "referer": "",
            "scraper": scraper,
            "translation": translation or "",
        })
        from .downloads import update as _track_update
        try:
            for ep_num in range(ep_start, ep_end + 1):
                ep_name = f"S{season_num:02d}E{ep_num:02d}"
                _resolve_and_play(show, season_num, ep_num, ep_name, scraper, player, quality, info_only, download, translation=translation, range_track_id=range_track_id)
                _save_history(ep_num)
                console.print()
        except KeyboardInterrupt:
            _track_update(range_track_id, status="interrupted")
            raise
        _track_update(range_track_id, status="completed")
        return

    ep_num = ep_start
    while True:
        proc = _resolve_and_play(show, season_num, ep_num, ep_name, scraper, player, quality, info_only, download, translation=translation)

        if proc is None or info_only or download:
            return

        try:
            proc.wait()
        except AttributeError:
            return

        _save_history(ep_num)

        theme = get_theme()
        console.print()

        try:
            choice = _select(
                "Options",
                choices=[
                    questionary.Choice(title="Next episode", value="next"),
                    questionary.Choice(title="Previous episode", value="prev"),
                    questionary.Choice(title="Replay", value="replay"),
                    questionary.Choice(title="Change quality", value="quality"),
                    questionary.Choice(title="Quit", value="quit"),
                ],
            )
        except Exception:
            return

        if not choice or choice == "quit":
            return
        elif choice == "next":
            ep_num += 1
            ep_name = f"S{season_num:02d}E{ep_num:02d}"
        elif choice == "prev":
            ep_num = max(1, ep_num - 1)
            ep_name = f"S{season_num:02d}E{ep_num:02d}"
        elif choice == "replay":
            pass
        elif choice == "quality":
            try:
                quality = _select(
                    "Quality",
                    choices=["480p", "720p", "1080p", "best", "worst"],
                    default=quality or "best",
                )
            except Exception:
                quality = Prompt.ask("Quality (480p, 720p, 1080p, best, worst)", default=quality or "best")


def _resolve_and_play(show, season_num, ep_num, ep_name, scraper, player, quality, info_only, download=False, translation=None, range_track_id=None):
    show_name = show.get("name", "?")
    show_id = show["id"]

    config = load_config()
    scraper_name = scraper or config.get("default_scraper", "example")
    scraper_instance = get_scraper(scraper_name)
    if not scraper_instance:
        available = [s["name"] for s in list_scrapers()]
        _print_error(
            f"Unknown scraper: [bold]{scraper_name}[/bold]",
            f"Available: {', '.join(available)}",
        )
        return None

    # Fallback chain: try the chosen scraper, then other builtin scrapers.
    # Only auto-fallback when no scraper was explicitly requested.
    builtins = [s["name"] for s in list_scrapers() if not s.get("optional")]
    if scraper:
        fallback_names = [scraper_name]
    else:
        fallback_names = [scraper_name] + [n for n in builtins if n != scraper_name]

    console.print()

    last_error = None
    for attempt_name in fallback_names:
        attempt = get_scraper(attempt_name)
        if not attempt:
            continue
        try:
            with console.status(f"Resolving via [bold]{attempt_name}[/bold]... (timeout {RESOLVE_TIMEOUT}s)", spinner="dots"):
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    info = {"show": show_name, "tv_id": show_id, "season": season_num, "episode": ep_num}
                    if quality:
                        info["quality"] = quality
                    if translation:
                        info["translation"] = translation
                    future = pool.submit(attempt.resolve, info)
                    result = future.result(timeout=RESOLVE_TIMEOUT)
            if result:
                scraper_name = attempt_name
                break
            last_error = f"Scraper [bold]{attempt_name}[/bold] returned nothing."
        except concurrent.futures.TimeoutError:
            last_error = f"Scraper [bold]{attempt_name}[/bold] timed out after {RESOLVE_TIMEOUT}s."
        except ScraperError as e:
            last_error = str(e)
            continue
    else:
        if last_error:
            _print_error(last_error)
        else:
            _print_error(f"No streaming source found for {show_name} {ep_name}.")
        return None

    if not result:
        _print_error(f"Scraper [bold]{scraper_name}[/bold] returned nothing.")
        return None

    theme = get_theme()
    console.clear()
    console.print(Panel(
        f"[{theme['success']}]Stream ready![/{theme['success']}]  [bold]{result.title}[/bold]",
        border_style=theme["success"],
    ))

    if info_only:
        console.print(f"  [{theme['dim']}]URL:[/{theme['dim']}] {result.m3u8_url}")
        return None

    if download:
        if result.m3u8_url.startswith("magnet:"):
            _print_error("Download not supported for magnet links.")
            return None
        if range_track_id:
            track_id = range_track_id
        else:
            from .downloads import create as _track_create
            track_id = _track_create({
                "title": result.title,
                "url": result.m3u8_url,
                "tv_id": show_id,
                "season": season_num,
                "episode": ep_num,
                "quality": quality,
                "referer": result.referer,
            })
        try:
            download_video(result.m3u8_url, title=result.title, referer=result.referer, track_id=track_id)
        except PlayerNotFoundError:
            _print_error(f"yt-dlp not found. Install it with: {ytdlp_install_hint()}")
            from .downloads import remove as _track_remove
            _track_remove(track_id)
        except PlayerLaunchError as e:
            _print_error(str(e))
            from .downloads import update as _track_update
            _track_update(track_id, status="error")
        except KeyboardInterrupt:
            raise
        return None

    player_choice = player or config.get("default_player", "auto")
    try:
        if result.m3u8_url.startswith("magnet:"):
            console.print(f"  [{theme['info']}]Connecting to torrent swarm...[/{theme['info']}]")
            play(result.m3u8_url, title=result.title, player=player_choice, season=season_num, episode=ep_num, referer=result.referer)
            return None  # magnets: can't wait for process
        else:
            console.print(f"  [{theme['info']}]Opening in {player_choice.upper()}...[/{theme['info']}]")
            return play(result.m3u8_url, title=result.title, player=player_choice, season=season_num, episode=ep_num, referer=result.referer)
    except PlayerNotFoundError as e:
        _print_error(str(e))
        return None
    except Exception as e:
        _print_error("Failed to launch player.", str(e))
        return None


def _play_movie(show, scraper, player, quality, info_only, download=False):
    """Resolve and play a movie (single stream, no season/episode)."""
    from .history import set_history as _set_history

    show_name = show.get("title", "?")
    show_id = show["id"]

    config = load_config()
    scraper_name = scraper or config.get("default_scraper", "webstream")
    scraper_instance = get_scraper(scraper_name)
    if not scraper_instance:
        available = [s["name"] for s in list_scrapers()]
        _print_error(
            f"Unknown scraper: [bold]{scraper_name}[/bold]",
            f"Available: {', '.join(available)}",
        )
        return

    console.print()
    try:
        with console.status(f"Resolving via [bold]{scraper_name}[/bold]... (timeout {RESOLVE_TIMEOUT}s)", spinner="dots"):
            with concurrent.futures.ThreadPoolExecutor() as pool:
                info = {"show": show_name, "movie_id": show_id, "media_type": "movie"}
                if quality:
                    info["quality"] = quality
                future = pool.submit(scraper_instance.resolve, info)
                result = future.result(timeout=RESOLVE_TIMEOUT)
    except concurrent.futures.TimeoutError:
        _print_error(f"Scraper [bold]{scraper_name}[/bold] timed out after {RESOLVE_TIMEOUT}s.")
        return
    except ScraperError as e:
        _print_error(str(e))
        return

    if not result:
        _print_error(f"Scraper [bold]{scraper_name}[/bold] returned nothing.")
        return

    theme = get_theme()
    console.clear()
    console.print(Panel(
        f"[{theme['success']}]Stream ready![/{theme['success']}]  [bold]{result.title}[/bold]",
        border_style=theme["success"],
    ))

    _set_history(show_name, None, None, scraper=scraper_name, quality=quality)

    if info_only:
        console.print(f"  [{theme['dim']}]URL:[/{theme['dim']}] {result.m3u8_url}")
        return

    if download:
        if result.m3u8_url.startswith("magnet:"):
            _print_error("Download not supported for torrent/magnet links.")
            return
        from .downloads import create as _track_create
        from .downloads import remove as _track_remove
        from .downloads import update as _track_update
        track_id = _track_create({
            "title": result.title,
            "url": result.m3u8_url,
            "tv_id": show_id,
            "season": None,
            "episode": None,
            "quality": quality or "",
            "referer": result.referer,
            "scraper": scraper_name,
        })
        try:
            download_video(result.m3u8_url, title=result.title, referer=result.referer, track_id=track_id)
        except PlayerNotFoundError:
            _print_error(f"yt-dlp not found. Install it with: {ytdlp_install_hint()}")
            _track_remove(track_id)
        except PlayerLaunchError as e:
            _print_error(str(e))
            _track_update(track_id, status="error")
        except KeyboardInterrupt:
            raise
        return

    player_choice = player or config.get("default_player", "auto")
    try:
        console.print(f"  [{theme['info']}]Opening in {player_choice.upper()}...[/{theme['info']}]")
        play(result.m3u8_url, title=result.title, player=player_choice, referer=result.referer)
    except PlayerNotFoundError as e:
        _print_error(str(e))
    except Exception as e:
        _print_error("Failed to launch player.", str(e))


# ---------------------------------------------------------------------------
# custom group (allows `cinnamon <query>` as shortcut for search)
# ---------------------------------------------------------------------------


class CinnamonGroup(click.Group):
    def resolve_command(self, ctx, args):
        if not args:
            return super().resolve_command(ctx, args)
        parent = super()
        cmd = parent.get_command(ctx, args[0])
        if cmd is not None:
            return super().resolve_command(ctx, args)
        cmd = parent.get_command(ctx, "search")
        return "search", cmd, args


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group(cls=CinnamonGroup, invoke_without_command=True)
@click.option("--setup", is_flag=True, help="Run the setup wizard")
@click.version_option(__version__, "--version", "-V")
@click.pass_context
def cli(ctx, setup):
    """Cinnamon - Stream TV shows, movies & anime from the command line."""
    if setup:
        ctx.invoke(setup_cmd)
        return
    if ctx.invoked_subcommand is None:
        if not get_tmdb_api_key():
            console.clear()
            console.print(Panel.fit(
                "[bold orange1]Welcome to Cinnamon![/bold orange1]",
                border_style="bright_yellow",
            ))
            console.print()
            if Confirm.ask("No API key found. Run setup?", default=True):
                ctx.invoke(setup_cmd)
                return
        theme = get_theme()
        console.clear()
        console.print(Panel.fit(
            f"[bold {theme['accent']}]Cinna[/bold {theme['accent']}][bold]mon[/bold]  [dim]v{__version__}[/dim]",
            border_style=theme["panel"],
        ))
        console.print()
        query = _prompt(f"[bold]Search for a[/bold] [{theme['info']}]show or movie[/{theme['info']}]")
        if query and query.strip():
            ctx.invoke(search, query=(query.strip(),))


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


@cli.command("setup")
def setup_cmd():
    """Run the setup wizard."""
    _setup_wizard()


def _setup_wizard():
    cfg = load_config()
    theme = get_theme()

    console.clear()
    console.print(Panel.fit(
        "[bold]⚙ Cinnamon Setup[/bold]",
        border_style=theme["panel"],
    ))
    console.print()

    # --- TMDB API Key ---
    existing_key = get_tmdb_api_key()
    if existing_key:
        console.print(f"  [{theme['success']}]✓[/] TMDB API key found")
        if not Confirm.ask("  Replace it?", default=False):
            api_key = existing_key
        else:
            api_key = _setup_api_key()
    else:
        api_key = _setup_api_key()

    if api_key and api_key != existing_key:
        cfg["tmdb_api_key"] = api_key
        save_config(cfg)

    # --- Default scraper ---
    from .scrapers import list_scrapers
    scrapers = list_scrapers()
    scraper_names = [s["name"] for s in scrapers]
    console.print()
    try:
        scraper_choice = _select(
            "Default scraper:",
            choices=[
                questionary.Choice(
                    title=f"{s['name']}  [dim]– {s['description']}[/dim]",
                    value=s["name"],
                ) for s in scrapers
            ],
            default=cfg.get("default_scraper", "vidsrc"),
        )
        if scraper_choice:
            cfg["default_scraper"] = scraper_choice
    except Exception:
        console.print(f"  [{theme['info']}]Scraper:[/] {cfg.get('default_scraper', 'vidsrc')}")

    # --- Default player ---
    console.print()
    try:
        player_choice = _select(
            "Default player:",
            choices=[
                questionary.Choice(title="auto  [dim]– detect mpv then VLC[/dim]", value="auto"),
                questionary.Choice(title="vlc", value="vlc"),
                questionary.Choice(title="mpv", value="mpv"),
            ],
            default=cfg.get("default_player", "auto"),
        )
        if player_choice:
            cfg["default_player"] = player_choice
    except Exception:
        pass

    # --- Theme ---
    console.print()
    try:
        theme_names = list(THEMES.keys())
        theme_choice = _select(
            "Color theme:",
            choices=[
                questionary.Choice(
                    title=_theme_preview(name),
                    value=name,
                ) for name in theme_names
            ],
            default=cfg.get("theme", "cinnamon"),
        )
        if theme_choice:
            cfg["theme"] = theme_choice
    except Exception:
        pass

    save_config(cfg)
    theme = get_theme()

    console.clear()
    console.print(Panel.fit(
        f"[{theme['success']}]✓ Setup complete![/]",
        border_style=theme["panel"],
    ))
    console.print(f"  [{theme['info']}]cinnamon[/]  –  quick search")
    console.print(f"  [{theme['info']}]cinnamon <show>[/]  –  search & play")
    console.print(f"  [{theme['info']}]cinnamon watch[/]  –  browse episodes")
    console.print()


def _setup_api_key():
    console.print()
    steps = [
        ("1", "Sign up", "https://www.themoviedb.org/signup"),
        ("2", "Verify your email"),
        ("3", "Visit", "https://www.themoviedb.org/settings/api"),
        ("4", 'Click "Create" under "Request an API Key"'),
        ("5", 'Choose "Developer"'),
        ("6", 'Fill in the form (any app name - e.g. "cinnamon")'),
        ("7", 'Copy the "API Key (v3 auth)" value'),
    ]

    for num, action, *rest in steps:
        url = rest[0] if rest else None
        if url:
            console.print(f"  [cyan]{num}.[/cyan] {action}  [underline]{url}[/underline]")
        else:
            console.print(f"  [cyan]{num}.[/cyan] {action}")

    if Confirm.ask("\nOpen step 1 in your browser?", default=True):
        webbrowser.open("https://www.themoviedb.org/signup")

    console.print()
    api_key = Prompt.ask("[bold]Paste your TMDB API Key[/bold]")
    if not api_key.strip():
        return None

    from .config import set_tmdb_api_key

    set_tmdb_api_key(api_key.strip())
    try:
        TMDBClient().search_tv("test")
        console.print(f"  [green]✓ API key verified![/green]")
        return api_key.strip()
    except CinnamonError:
        console.print(f"  [red]✗ Verification failed.[/red] Check key at https://www.themoviedb.org/settings/api")
        return api_key.strip()


def _theme_preview(name):
    descs = {"cinnamon": "warm orange & gold", "ocean": "cool blue & teal", "mono": "minimal white"}
    desc = descs.get(name, "")
    return f"{name}  —  {desc}"


# ---------------------------------------------------------------------------
# search  (also invoked via `cinnamon <query>` fallback)
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("query", nargs=-1, required=False)
@click.option("-t", "--type", "media_type", type=click.Choice(["tv", "movie"]), default=None, help="tv or movie (defaults to both)")
@click.option("-s", "--season", type=int, help="Season number")
@click.option("-e", "--episode", "ep_str", help="Episode number or range (e.g. 1 or 1-10)")
@click.option("--scraper", help="Scraper name")
@click.option("--player", help="Player: vlc, mpv, or auto")
@click.option("-q", "--quality", help="Video quality: 480p, 720p, 1080p, best, worst")
@click.option("-d", "--download", is_flag=True, help="Download instead of streaming")
@click.option("--info-only", is_flag=True, help="Show the m3u8 URL without playing")
@_handle_tmdb_error
def search(query, media_type, season, ep_str, scraper, player, quality, download, info_only):
    """Search for a show or movie, pick one, and watch it."""
    _check_for_updates()
    tmdb = _get_tmdb()

    ep_start, ep_end = _parse_episode(ep_str) if ep_str else (None, None)

    query_str = " ".join(query) if query else None
    if not query_str:
        console.clear()
        query_str = Prompt.ask("[bold]Search for a[/bold] [cyan]show or movie[/cyan]")

    if media_type == "tv":
        combined = [dict(r, _media_type="tv") for r in tmdb.search_tv(query_str).get("results", [])]
    elif media_type == "movie":
        combined = [dict(r, _media_type="movie") for r in tmdb.search_movie(query_str).get("results", [])]
    else:
        tv = [dict(r, _media_type="tv") for r in tmdb.search_tv(query_str).get("results", [])]
        movie = [dict(r, _media_type="movie") for r in tmdb.search_movie(query_str).get("results", [])]
        combined = tv + movie

    if not combined:
        _print_info(f"No results found for \"{query_str}\".")
        return

    show = _pick_combined(combined, "Select a title:")

    if not show:
        return

    mtype = show.get("_media_type", "tv")
    title_key = "name" if mtype == "tv" else "title"
    date_key = "first_air_date" if mtype == "tv" else "release_date"
    show_name = show.get(title_key, "?")
    show_id = show["id"]

    if scraper is None and mtype == "tv" and _is_anime(show):
        # Route anime through allanime's available-episode list so we never
        # offer an episode the source doesn't have (same as `cinnamon anime`).
        from .scrapers.anime import _find_show, _allanime_episodes
        import requests as _req
        _as = _req.Session()
        _as.headers.update({"User-Agent": "Mozilla/5.0"})
        _aid = _find_show(_as, show_name)
        if _aid:
            _ed = _allanime_episodes(_as, _aid)
            if _ed:
                _run_anime_flow(show_name, _ed, season, ep_str, player, quality, info_only, download)
                return
        # Fall through to generic TV flow if allanime lookup fails.
        scraper = "anime"
        _print_info(f"Detected anime — using [bold]anime[/bold] scraper")

    if mtype == "movie":
        _play_movie(show, scraper, player, quality, info_only, download)
        return

    if season is not None and ep_start is not None:
        _play_with_menu(show, season, ep_start, ep_end, f"S{season:02d}E{ep_start:02d}", scraper, player, quality, info_only, download)
        return

    theme = get_theme()
    console.clear()
    console.print(Panel(f"[bold {theme['accent']}]{show_name}[/bold {theme['accent']}]", border_style=theme["border"]))

    _interactive_episode_picker(tmdb, show, scraper, player, quality, info_only, download, ep_start, ep_end)


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--query", help="Search query (omit for interactive)")
@click.option("--id", "tmdb_id", type=int, help="TMDB show/movie ID")
@click.option("-t", "--type", "media_type", type=click.Choice(["tv", "movie"]), default=None, help="tv or movie (defaults to both)")
@click.option("-s", "--season", type=int, help="Season number")
@click.option("-e", "--episode", "ep_str", help="Episode number or range (e.g. 1 or 1-10)")
@click.option("--scraper", help="Scraper name")
@click.option("--player", help="Player: vlc, mpv, or auto")
@click.option("-d", "--download", is_flag=True, help="Download instead of streaming")
@click.option("--info-only", is_flag=True, help="Show the m3u8 URL without playing")
@click.option("-q", "--quality", help="Video quality: 480p, 720p, 1080p, best, worst")
@_handle_tmdb_error
def watch(query, tmdb_id, media_type, season, ep_str, scraper, player, download, info_only, quality):
    """Browse episodes interactively and play one."""
    _check_for_updates()
    tmdb = _get_tmdb()

    ep_start, ep_end = _parse_episode(ep_str) if ep_str else (None, None)

    # Explicit movie request.
    if media_type == "movie":
        if not tmdb_id and query:
            results = tmdb.search_movie(query).get("results", [])
            show = _pick_with_arrows(results, "title", "release_date", "Select a movie:")
            if not show:
                return
            tmdb_id = show["id"]
        elif tmdb_id:
            show = tmdb.get_movie_details(tmdb_id)
        else:
            query = _prompt("Search for a movie")
            results = tmdb.search_movie(query).get("results", [])
            show = _pick_with_arrows(results, "title", "release_date", "Select a movie:")
            if not show:
                return
        _play_movie(show, scraper, player, quality, info_only, download)
        return

    # Explicit TV request (or a TMDB id with no type hint).
    if media_type == "tv" or (tmdb_id and media_type is None):
        if tmdb_id:
            show = tmdb.get_tv_details(tmdb_id)
        elif query:
            results = tmdb.search_tv(query).get("results", [])
            show = _pick_with_arrows(results, "name", "first_air_date", "Select a show:")
            if not show:
                return
        else:
            query = _prompt("Search for a show")
            results = tmdb.search_tv(query).get("results", [])
            show = _pick_with_arrows(results, "name", "first_air_date", "Select a show:")
            if not show:
                return
        if scraper is None and _is_anime(show):
            scraper = "anime"
            _print_info(f"Detected anime — using [bold]anime[/bold] scraper")
        if season is not None and ep_start is not None:
            _play_with_menu(show, season, ep_start, ep_end, f"E{ep_start}", scraper, player, quality, info_only, download)
            return
        _interactive_episode_picker(tmdb, show, scraper, player, quality, info_only, ep_start=ep_start, ep_end=ep_end)
        return

    # No type given: search both TV and movies, then dispatch by what is picked.
    if tmdb_id:
        # Ambiguous id without a type — try TV first, fall back to movie.
        try:
            show = tmdb.get_tv_details(tmdb_id)
            mtype = "tv"
        except TMDBNotFoundError:
            show = tmdb.get_movie_details(tmdb_id)
            mtype = "movie"
    elif query:
        tv = [dict(r, _media_type="tv") for r in tmdb.search_tv(query).get("results", [])]
        movie = [dict(r, _media_type="movie") for r in tmdb.search_movie(query).get("results", [])]
        combined = tv + movie
        if not combined:
            _print_info(f"No results found for \"{query}\".")
            return
        show = _pick_combined(combined, "Select a title:")
        if not show:
            return
        mtype = show.get("_media_type", "tv")
    else:
        query = _prompt("[bold]Search for a[/bold] [cyan]show or movie[/cyan]")
        if not query or not query.strip():
            return
        query = query.strip()
        tv = [dict(r, _media_type="tv") for r in tmdb.search_tv(query).get("results", [])]
        movie = [dict(r, _media_type="movie") for r in tmdb.search_movie(query).get("results", [])]
        combined = tv + movie
        if not combined:
            _print_info(f"No results found for \"{query}\".")
            return
        show = _pick_combined(combined, "Select a title:")
        if not show:
            return
        mtype = show.get("_media_type", "tv")

    if mtype == "movie":
        _play_movie(show, scraper, player, quality, info_only, download)
        return

    if scraper is None and _is_anime(show):
        scraper = "anime"
        _print_info(f"Detected anime — using [bold]anime[/bold] scraper")
    if season is not None and ep_start is not None:
        _play_with_menu(show, season, ep_start, ep_end, f"E{ep_start}", scraper, player, quality, info_only, download)
        return
    _interactive_episode_picker(tmdb, show, scraper, player, quality, info_only, ep_start=ep_start, ep_end=ep_end)


# ---------------------------------------------------------------------------
# shared: interactive episode picker + resolve + play
# ---------------------------------------------------------------------------


def _interactive_episode_picker(tmdb, show, scraper, player, quality, info_only, download=False, ep_start=None, ep_end=None):
    show_name = show.get("name", "?")
    show_id = show["id"]
    details = tmdb.get_tv_details(show_id)
    total = details.get("number_of_seasons", 0)
    if total == 0:
        _print_error(f"No season data for {show_name}.")
        return

    if total == 1:
        season_num = 1
        console.print(f"  [dim]Only one season — using Season 1[/dim]")
    else:
        try:
            season_choices = [questionary.Choice(title=f"Season {i}", value=i) for i in range(1, total + 1)]
            season_chosen = _select("Select a season:", choices=season_choices)
            if not season_chosen:
                return
            season_num = season_chosen
        except Exception:
            season_num = Prompt.ask("Season", default="1")
            try:
                season_num = int(season_num)
            except ValueError:
                _print_error("Invalid season number.")
                return

    try:
        season_data = tmdb.get_season_details(show_id, season_num)
    except TMDBNotFoundError:
        _print_error(f"Season {season_num} not found for {show_name}.")
        return

    episodes = season_data.get("episodes", [])
    if not episodes:
        _print_error(f"No episodes found for S{season_num}.")
        return

    if ep_start is None:
        from .history import get_history as _get_history
        last = _get_history(show_name)
        if last and last.get("season") == season_num and last.get("episode"):
            # Suggest the next unwatched episode (last watched + 1) when it
            # exists in this season; otherwise fall back to the last watched.
            resume_ep = last["episode"] + 1
            if not any(
                isinstance(ep.get("episode_number"), int) and ep["episode_number"] == resume_ep
                for ep in episodes
            ):
                resume_ep = last["episode"]
            try:
                answer = Prompt.ask(
                    f"  Resume from [bold]E{resume_ep:02d}[/bold]? [dim](y/n)[/dim]",
                    default="y",
                    show_default=False,
                ).strip().lower()
                resume = answer in ("", "y", "yes")
            except (EOFError, KeyboardInterrupt):
                resume = True
            if resume:
                ep_start = resume_ep

    if ep_start is not None:
        ep_name = f"S{season_num:02d}E{ep_start:02d}"
        _play_with_menu(show, season_num, ep_start, ep_end, ep_name, scraper, player, quality, info_only, download)
        return

    try:
        ep_choices = []
        for ep in episodes:
            ep_num = ep.get("episode_number", "?")
            ep_title = ep.get("name", f"Episode {ep_num}")
            label = f"E{ep_num:02d}  {ep_title}" if isinstance(ep_num, int) else f"{ep_num}  {ep_title}"
            ep_choices.append(questionary.Choice(title=label, value=ep))
        ep_chosen = _select(
            f"Season {season_num} - Select an episode:",
            choices=ep_choices,
        )
        if not ep_chosen:
            return
    except Exception:
        ep_chosen = _pick_numbered(episodes, "name", "air_date", "Select an episode")
        if not ep_chosen:
            return

    ep_num = ep_chosen["episode_number"]
    ep_name = ep_chosen.get("name", f"E{ep_num}")

    _play_with_menu(show, season_num, ep_num, None, ep_name, scraper, player, quality, info_only, download)


# ---------------------------------------------------------------------------
# play-url
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("url")
@click.option("--player", help="Player: vlc, mpv, or auto")
@click.option("--title", default="", help="Media title")
def play_url(url, player, title):
    """Play a direct m3u8 URL in VLC or mpv."""
    config = load_config()
    player_choice = player or config.get("default_player", "auto")

    try:
        play(url, title=title, player=player_choice)
        _print_success(f"Launched in {player_choice.upper()}.")
    except PlayerNotFoundError as e:
        _print_error(str(e))
    except ValueError as e:
        _print_error(str(e))


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------


@cli.command()
@_handle_tmdb_error
def resume():
    """List interrupted downloads and resume one."""
    from .downloads import get, list_all, update as _track_update

    dls = list_all(status="interrupted")
    if not dls:
        _print_info("No interrupted downloads found.")
        return

    console.print()
    table = Table(border_style="dim")
    table.add_column("#", style="cyan")
    table.add_column("Title")
    table.add_column("Episodes")
    table.add_column("Quality", style="yellow")
    table.add_column("Progress", style="green")

    resume_indices = []
    for i, d in enumerate(dls, 1):
        ep = d.get("episode", "")
        season = d.get("season")
        ep_label = f"S{season}E{ep}" if season and ep else str(ep)
        if d.get("url") or (not d.get("url") and "-" in str(ep)):
            resume_indices.append(i)
        else:
            ep_label += " [dim](can't resume)[/dim]"
        table.add_row(str(i), d.get("title", "?"), ep_label, d.get("quality", "-"), "[yellow]interrupted[/yellow]")

    console.print(table)

    if not resume_indices:
        console.print("  [dim]No resumable entries found.[/dim]")
        if _prompt("  Remove these entries?", default="y").strip().lower() in ("y", "yes"):
            for d in dls:
                _track_remove(d["id"])
            _print_success("Cleaned up.")
        return

    choice = _prompt("Resume which download?", default=str(resume_indices[0]))
    try:
        d = dls[int(choice) - 1]
    except (ValueError, IndexError):
        return

    track_id = d["id"]
    url = d.get("url")
    title = d.get("title", "?")
    season = d.get("season")
    ep_raw = d.get("episode", "")

    if not url and "-" in str(ep_raw):
        ep_parts = str(ep_raw).split("-", 1)
        try:
            ep_start, ep_end = int(ep_parts[0]), int(ep_parts[1])
        except ValueError:
            _print_error("Invalid episode range in download entry.")
            return
        show_dict = {"name": title, "id": d.get("tv_id", 0)}
        scraper = d.get("scraper", "anime")
        quality = d.get("quality")
        translation = d.get("translation") or None
        _track_update(track_id, status="queued")
        _play_with_menu(show_dict, season or 1, ep_start, ep_end, "", scraper, None, quality, False, True, translation=translation)
        return

    if not url:
        _print_error("Cannot resume this download entry (no URL).")
        return
    referer = d.get("referer")

    _track_update(track_id, status="queued")

    try:
        download_video(url, title=title, referer=referer, track_id=track_id)
    except PlayerNotFoundError:
        _print_error(f"yt-dlp not found. Install it with: {ytdlp_install_hint()}")
        _track_update(track_id, status="interrupted")
    except PlayerLaunchError as e:
        _print_error(str(e))
        _track_update(track_id, status="error")
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


@cli.group()
def download():
    """Manage downloads."""


@download.command("list")
def download_list():
    """Show all tracked downloads."""
    from .downloads import list_all, remove as _track_remove

    all_dls = list_all()
    if not all_dls:
        _print_info("No downloads tracked.")
        return

    table = Table(border_style="dim")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Episodes")
    table.add_column("Quality", style="yellow")
    table.add_column("Status")
    table.add_column("Date")

    for d in all_dls:
        ep = d.get("episode", "")
        season = d.get("season")
        ep_label = f"S{season}E{ep}" if season and ep else str(ep)
        ts = d.get("timestamp", 0)
        import datetime
        date_label = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
        table.add_row(
            d.get("id", "?"),
            d.get("title", "?"),
            ep_label,
            d.get("quality", "-"),
            d.get("status", "?"),
            date_label,
        )

    console.print(table)

    if _prompt("Clear completed/interrupted?", default="n").strip().lower() in ("y", "yes"):
        for d in all_dls:
            if d["status"] in ("completed", "error"):
                _track_remove(d["id"])
        _print_success("Cleaned up.")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@cli.group()
def config():
    """View or change settings."""


@config.command("show")
def config_show():
    """Show current configuration."""
    cfg = load_config()
    masked = cfg.get("tmdb_api_key", "")
    if masked:
        if len(masked) > 10:
            masked = masked[:6] + "*" * (len(masked) - 6)
        else:
            masked = masked[:3] + "***"

    table = Table(border_style="dim")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("TMDB API Key", masked or "[dim]not set[/dim]")
    table.add_row("Default scraper", cfg.get("default_scraper", "example"))
    table.add_row("Default player", cfg.get("default_player", "auto"))
    table.add_row("Theme", cfg.get("theme", "cinnamon"))

    scrapers_cfg = cfg.get("scrapers", {})
    for name, sc in scrapers_cfg.items():
        for k, v in sc.items():
            table.add_row(f"scraper.{name}.{k}", str(v))

    console.print(table)


@config.command("set-api-key")
@click.argument("api_key")
def config_set_api_key(api_key):
    """Set your TMDB API key."""
    from .config import set_tmdb_api_key

    set_tmdb_api_key(api_key)
    _print_success("TMDB API key saved.")


@config.command("show-api-key")
def config_show_api_key():
    """Show the active TMDB API key (env var or saved config) and its source."""
    import os
    env_key = os.getenv("TMDB_API_KEY")
    if env_key:
        console.print(f"  Source: [cyan]TMDB_API_KEY[/cyan] env var")
        console.print(f"  Key: [bold]{env_key}[/bold]")
        return
    from .config import get_tmdb_api_key
    key = get_tmdb_api_key()
    if key:
        console.print("  Source: [yellow]config.json[/yellow]")
        console.print(f"  Key: [bold]{key}[/bold]")
    else:
        _print_info("No TMDB API key set (env var or config).")


@config.command("default-scraper")
@click.argument("name")
def config_default_scraper(name):
    """Set the default scraper."""
    available = [s["name"] for s in list_scrapers()]
    if name not in available:
        _print_error(f"Unknown scraper: {name}", f"Available: {', '.join(available)}")
        return
    cfg = load_config()
    cfg["default_scraper"] = name
    save_config(cfg)
    _print_success(f"Default scraper set to [bold]{name}[/bold].")


@config.command("default-player")
@click.argument("player", type=click.Choice(["auto", "vlc", "mpv"]))
def config_default_player(player):
    """Set the default player (auto, vlc, or mpv)."""
    cfg = load_config()
    cfg["default_player"] = player
    save_config(cfg)
    _print_success(f"Default player set to [bold]{player}[/bold].")


@config.group("scraper")
def config_scraper():
    """Configure a specific scraper."""


@config_scraper.command("set")
@click.argument("name")
@click.argument("key")
@click.argument("value")
def config_scraper_set(name, key, value):
    """Set a config option for a scraper."""
    available = [s["name"] for s in list_scrapers()]
    if name not in available:
        _print_error(f"Unknown scraper: {name}", f"Available: {', '.join(available)}")
        return
    set_scraper_config(name, key, value)
    _print_success(f"Scraper [bold]{name}[/bold] {key} = {value}")


@config_scraper.command("show")
@click.argument("name")
def config_scraper_show(name):
    """Show config for a specific scraper."""
    sc_cfg = get_scraper_config(name)
    if not sc_cfg:
        _print_info(f"No config set for scraper [bold]{name}[/bold].")
        return
    table = Table(border_style="dim")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    for k, v in sc_cfg.items():
        table.add_row(k, str(v))
    console.print(table)


# ---------------------------------------------------------------------------
# scrapers
# ---------------------------------------------------------------------------


@cli.command()
def scrapers():
    """List available scrapers."""
    all_scrapers = list_scrapers()
    if not all_scrapers:
        _print_info("No scrapers found.")
        return

    table = Table(border_style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Source", style="yellow")

    for s in all_scrapers:
        source = "built-in" if s.get("builtin") else "user"
        table.add_row(s["name"], s["description"], source)

    console.print(table)

    from .scrapers import _OPTIONAL_SCRAPERS
    if _OPTIONAL_SCRAPERS:
        console.print()
        console.print("[dim]Optional (install via[/dim] [cyan]cinnamon install <name>[/cyan][dim]):[/dim]")
        for name, info in _OPTIONAL_SCRAPERS.items():
            console.print(f"  [cyan]{name}[/cyan]  {info['description']}  [dim](needs: {info['deps']})[/dim]")
    console.print(
        "\n[dim]Tip: Drop a .py scraper in[/dim]"
        f" [cyan]{get_ensured_dirs()[1]}[/cyan]"
        "\n[dim]or set[/dim] [cyan]CINNAMON_SCRAPERS_PATH[/cyan] [dim]env var.[/dim]"
    )


@cli.command()
@click.argument("name")
def install(name):
    """Install an optional scraper (vidsrc, torrentio)."""
    from .scrapers import _OPTIONAL_SCRAPERS, install_optional

    if name not in _OPTIONAL_SCRAPERS:
        available = ", ".join(_OPTIONAL_SCRAPERS)
        _print_error(f"Unknown optional scraper: {name}", f"Available: {available}")
        return

    try:
        dst = install_optional(name)
        _print_success(f"Installed [bold]{name}[/bold] scraper", f"Saved to {dst}")
    except Exception as e:
        _print_error(f"Failed to install {name}", str(e))


@cli.command()
@click.argument("query", nargs=-1, required=False)
@click.option("-s", "--season", type=int, help="Season number")
@click.option("-e", "--episode", "ep_str", help="Episode number or range (e.g. 1 or 1-10)")
@click.option("-d", "--download", is_flag=True, help="Download instead of streaming")
@click.option("--player", help="Player: vlc, mpv, or auto")
@click.option("-q", "--quality", help="Video quality: 480p, 720p, 1080p, best, worst")
@click.option("--info-only", is_flag=True, help="Show the stream URL without playing")
def anime(query, season, ep_str, download, player, quality, info_only):
    """Search anime via AniList (no API key needed) and stream from allanime."""
    _check_for_updates()

    query_str = " ".join(query) if query else None
    if not query_str:
        query_str = Prompt.ask("[bold]Search for an[/bold] [magenta]anime[/magenta]")
    from .anilist import search_anime

    results = search_anime(query_str)
    if not results:
        _print_info(f"No anime found for \"{query_str}\".")
        return

    def _title(m):
        return m.get("title", {}).get("romaji") or m.get("title", {}).get("english") or m.get("title", {}).get("native", "?")
    def _year(m):
        sd = m.get("startDate") or {}
        return str(sd.get("year", "")) if sd.get("year") else ""

    ql = query_str.lower().strip()
    def _relevance(m):
        t = _title(m).lower()
        if t == ql:
            return 0
        if t.startswith(ql):
            return 1
        if ql in t:
            return 2
        return 3

    results.sort(key=lambda m: (_relevance(m), _title(m).lower()))

    show = _pick_with_arrows(results, _title, _year, "Select an anime:")

    if not show:
        return

    show_name = _title(show)
    theme = get_theme()
    console.clear()
    console.print(Panel(f"[bold {theme['accent']}]{show_name}[/bold {theme['accent']}]", border_style=theme["border"]))

    from .history import get_history as _get_history
    if not ep_str:
        last = _get_history(show_name)
        if last and last.get("episode"):
            # Suggest the next unwatched episode (last watched + 1).
            resume_ep = last["episode"] + 1
            try:
                answer = Prompt.ask(
                    f"  Resume from [bold]S{last.get('season', 1)}E{resume_ep}[/bold]? [dim](y/n)[/dim]",
                    default="y",
                    show_default=False,
                ).strip().lower()
                resume = answer in ("", "y", "yes")
            except (EOFError, KeyboardInterrupt):
                resume = True
            if resume:
                ep_str = str(resume_ep)

    from .scrapers.anime import _find_show, _allanime_episodes
    import requests as _req

    session = _req.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    allanime_id = _find_show(session, show_name)
    if not allanime_id:
        _print_error(f"No match for \"{show_name}\" on allanime.")
        return

    episodes_detail = _allanime_episodes(session, allanime_id)
    if not episodes_detail:
        _print_error("No episode data from allanime.")
        return

    _run_anime_flow(show_name, episodes_detail, season, ep_str, player, quality, info_only, download)


def _run_anime_flow(show_name, episodes_detail, season=None, ep_str=None, player=None, quality=None, info_only=False, download=False):
    """Drive the episode picker from allanime's *available* episodes (not TMDB's
    full list), so we never offer an episode the anime source doesn't have."""
    parsed = {}
    for key, eps in episodes_detail.items():
        if "|" in key:
            parts = key.split("|", 1)
            s = int(parts[0]) if parts[0].isdigit() else 1
            tt = parts[1] if len(parts) > 1 else "sub"
        else:
            s = 1
            tt = key
        parsed.setdefault(s, {})[tt] = eps

    if season is None:
        season_keys = sorted(parsed.keys())
        if len(season_keys) > 1:
            try:
                season = _select("Select a season:", choices=[
                    questionary.Choice(title=f"Season {s}", value=s) for s in season_keys
                ])
            except Exception:
                season = season_keys[0]
        else:
            season = season_keys[0]
            if season != 1:
                console.print(f"  [dim]Using Season {season}[/dim]")

    season_data = parsed.get(season)
    if not season_data:
        _print_error(f"No episodes for season {season}.")
        return

    tt_keys = list(season_data.keys())
    if "sub" in tt_keys and len(tt_keys) > 1:
        try:
            tt = _select("Translation:", choices=[
                questionary.Choice(title=k, value=k) for k in tt_keys
            ], default="sub")
        except Exception:
            tt = "sub"
    else:
        tt = tt_keys[0]
        if tt != "sub":
            console.print(f"  [dim]Using {tt}[/dim]")

    episodes = [int(e) for e in season_data[tt]]
    max_ep = max(episodes)
    ep_start, ep_end = _parse_episode(ep_str) if ep_str else (None, None)

    if ep_start is not None:
        if ep_start not in episodes:
            # The suggested next episode may not exist yet (e.g. unaired) —
            # fall back to the last available episode instead of hard-erroring.
            fallback = max_ep
            _print_info(f"Episode {ep_start} not available yet — using E{fallback}.")
            ep_start = fallback
        if ep_end is not None and ep_end > max_ep:
            ep_end = max_ep
    else:
        try:
            ep_choices = [questionary.Choice(title=f"Episode {e}", value=e) for e in sorted(episodes)]
            ep_chosen = _select("Select an episode:", choices=ep_choices)
            if not ep_chosen:
                return
            ep_start = int(ep_chosen)
        except Exception:
            ep_start = Prompt.ask("Episode", default="1")
            try:
                ep_start = int(ep_start)
            except ValueError:
                _print_error("Invalid episode number.")
                return

    scraper = "anime"

    show_dict = {"name": show_name, "id": 0}
    ep_name = f"S{season:02d}E{ep_start:02d}"
    _play_with_menu(show_dict, season, ep_start, ep_end, ep_name, scraper, player, quality, info_only, download, translation=tt)


@cli.command()
def update():
    """Check for and install the latest version of cinnamon from GitHub."""
    theme = get_theme()

    latest = _latest_version()
    if not latest:
        _print_error("Could not determine latest version from GitHub.", "Make sure you have internet access.")
        return

    current = __version__
    cur = tuple(map(int, current.split(".")))
    lat = tuple(map(int, latest.split(".")))

    if lat <= cur:
        _print_success(f"Already up to date ({current}).")
        return

    console.print(f"  [{theme['info']}]Updating:[/] {current} → [bold]{latest}[/bold]")
    console.print()

    url = f"https://github.com/{_UPDATE_REPO}/archive/refs/tags/v{latest}.tar.gz"
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "--upgrade", url],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            console.print(f"  {line.rstrip()}")
        proc.wait()

        if proc.returncode == 0:
            cfg = load_config()
            cfg["_update_check"] = 0
            save_config(cfg)
            try:
                import importlib
                import cinnamon as _pkg
                importlib.reload(_pkg)
                new_version = _pkg.__version__
            except Exception:
                new_version = None
            if new_version and new_version != current:
                _print_success(f"Updated to {new_version}!")
            else:
                _print_error(
                    f"pip reported success but version is still {current}.",
                    "You may be installing into a different Python environment. Try: "
                    f"python -m pip install --upgrade {url}",
                )
        else:
            _print_error(f"Update failed (exit code {proc.returncode}).")
    except Exception as e:
        _print_error("Update failed.", str(e))


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("query", nargs=-1, required=False)
@click.option("--clear", is_flag=True, help="Clear all watch history")
def history(query, clear):
    """Show watch history and resume from last episode."""
    from .history import clear_history, get_history, list_history

    if clear:
        clear_history()
        _print_success("Watch history cleared.")
        return

    q = " ".join(query) if query else None
    if q:
        entry = get_history(q)
        if not entry:
            _print_info(f"No history found for \"{q}\".")
            return
        _print_info(f"Last watched [bold]{q}[/bold]: S{entry.get('season', 1)}E{entry.get('episode')}")
        _play_with_menu(
            {"name": q, "id": 0},
            entry.get("season", 1),
            entry.get("episode"),
            None,
            "",
            entry.get("scraper") or "anime",
            None,
            entry.get("quality"),
            False,
            False,
            translation=entry.get("translation"),
        )
        return

    entries = list_history()
    if not entries:
        _print_info("No watch history yet.")
        return

    table = Table(border_style="dim")
    table.add_column("Show", style="cyan")
    table.add_column("Episode", style="green")
    table.add_column("Last watched", style="yellow")

    import datetime
    for name, e in entries:
        ts = e.get("timestamp", 0)
        date_label = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
        table.add_row(name, f"S{e.get('season', 1)}E{e.get('episode')}", date_label)

    console.print(table)

    if _prompt("  Clear all history?", default="n").strip().lower() in ("y", "yes"):
        clear_history()
        _print_success("Watch history cleared.")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
