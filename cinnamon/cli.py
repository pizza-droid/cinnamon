import concurrent.futures
import subprocess
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


_UPDATE_CHECK_CACHE = 86400  # 24 hours


_UPDATE_REPO = "pizza-droid/cinnamon"


_UPDATE_CHECK_FALLBACK_DAYS = 7


def _check_for_updates():
    try:
        cfg = load_config()
        last_check = cfg.get("_update_check", 0)
        if time.time() - last_check < _UPDATE_CHECK_CACHE:
            return

        import requests
        resp = requests.get(
            f"https://api.github.com/repos/{_UPDATE_REPO}/tags",
            timeout=5,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code != 200:
            return
        tags = resp.json()
        if not tags:
            return
        latest = tags[0].get("name", "").lstrip("v")
        if not latest:
            return

        cfg["_update_check"] = time.time()
        save_config(cfg)

        current = __version__
        if latest == current:
            return

        cur = tuple(map(int, current.split(".")))
        lat = tuple(map(int, latest.split(".")))
        if lat > cur:
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
        return questionary.select(message, choices=choices).unsafe_ask()
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
    while True:
        try:
            choice = int(Prompt.ask(f"{message} (enter number)", default="1"))
            if 1 <= choice <= len(items):
                return items[choice - 1]
            console.print(f"[red]Pick a number between 1 and {len(items)}.[/red]")
        except ValueError:
            console.print("[red]Invalid input. Enter a number.[/red]")
        except (EOFError, KeyboardInterrupt):
            console.print()
            raise SystemExit(0)


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


def _play_with_menu(show, season_num, ep_start, ep_end, ep_name, scraper, player, quality, info_only, download=False):
    """Play episode(s), then show interactive menu until user quits."""

    if ep_end is not None and ep_end > ep_start:
        if not download:
            _print_error("Episode ranges are only supported with --download.")
            return
        for ep_num in range(ep_start, ep_end + 1):
            ep_name = f"S{season_num:02d}E{ep_num:02d}"
            _resolve_and_play(show, season_num, ep_num, ep_name, scraper, player, quality, info_only, download)
            console.print()
        return

    ep_num = ep_start
    while True:
        proc = _resolve_and_play(show, season_num, ep_num, ep_name, scraper, player, quality, info_only, download)

        if proc is None or info_only or download:
            return

        try:
            proc.wait()
        except AttributeError:
            return

        theme = get_theme()
        console.print()

        try:
            choice = questionary.select(
                "Options",
                choices=[
                    questionary.Choice(title="Next episode", value="next"),
                    questionary.Choice(title="Previous episode", value="prev"),
                    questionary.Choice(title="Replay", value="replay"),
                    questionary.Choice(title="Change quality", value="quality"),
                    questionary.Choice(title="Quit", value="quit"),
                ],
            ).unsafe_ask()
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
                quality = questionary.select(
                    "Quality",
                    choices=["480p", "720p", "1080p", "best", "worst"],
                    default=quality or "best",
                ).unsafe_ask()
            except Exception:
                quality = Prompt.ask("Quality (480p, 720p, 1080p, best, worst)", default=quality or "best")


def _resolve_and_play(show, season_num, ep_num, ep_name, scraper, player, quality, info_only, download=False):
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

    console.print()

    try:
        with console.status(f"Resolving via [bold]{scraper_name}[/bold]... (timeout {RESOLVE_TIMEOUT}s)", spinner="dots"):
            with concurrent.futures.ThreadPoolExecutor() as pool:
                info = {"show": show_name, "tv_id": show_id, "season": season_num, "episode": ep_num}
                if quality:
                    info["quality"] = quality
                future = pool.submit(scraper_instance.resolve, info)
                result = future.result(timeout=RESOLVE_TIMEOUT)
    except concurrent.futures.TimeoutError:
        _print_error(
            f"Scraper [bold]{scraper_name}[/bold] timed out after {RESOLVE_TIMEOUT}s.",
            "The streaming source may be down or unreachable. Try another scraper or episode.",
        )
        return None
    except ScraperError as e:
        _print_error(str(e))
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
        except KeyboardInterrupt:
            pass
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
    """Cinnamon - Stream TV shows & movies from the command line."""
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
        query = Prompt.ask(f"[bold]Search for a[/bold] [{theme['info']}]TV show[/{theme['info']}]")
        if query.strip():
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
        scraper_choice = questionary.select(
            "Default scraper:",
            choices=[
                questionary.Choice(
                    title=f"{s['name']}  [dim]– {s['description']}[/dim]",
                    value=s["name"],
                ) for s in scrapers
            ],
            default=cfg.get("default_scraper", "vidsrc"),
        ).unsafe_ask()
        if scraper_choice:
            cfg["default_scraper"] = scraper_choice
    except Exception:
        console.print(f"  [{theme['info']}]Scraper:[/] {cfg.get('default_scraper', 'vidsrc')}")

    # --- Default player ---
    console.print()
    try:
        player_choice = questionary.select(
            "Default player:",
            choices=[
                questionary.Choice(title="auto  [dim]– detect mpv then VLC[/dim]", value="auto"),
                questionary.Choice(title="vlc", value="vlc"),
                questionary.Choice(title="mpv", value="mpv"),
            ],
            default=cfg.get("default_player", "auto"),
        ).unsafe_ask()
        if player_choice:
            cfg["default_player"] = player_choice
    except Exception:
        pass

    # --- Theme ---
    console.print()
    try:
        theme_names = list(THEMES.keys())
        theme_choice = questionary.select(
            "Color theme:",
            choices=[
                questionary.Choice(
                    title=_theme_preview(name),
                    value=name,
                ) for name in theme_names
            ],
            default=cfg.get("theme", "cinnamon"),
        ).unsafe_ask()
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
@click.option("-t", "--type", "media_type", type=click.Choice(["tv", "movie"]), default="tv")
@click.option("-s", "--season", type=int, help="Season number")
@click.option("-e", "--episode", "ep_str", help="Episode number or range (e.g. 1 or 1-10)")
@click.option("--scraper", help="Scraper name")
@click.option("--player", help="Player: vlc, mpv, or auto")
@click.option("-q", "--quality", help="Video quality: 480p, 720p, 1080p, best, worst")
@click.option("-d", "--download", is_flag=True, help="Download instead of streaming")
@click.option("--info-only", is_flag=True, help="Show the m3u8 URL without playing")
@_handle_tmdb_error
def search(query, media_type, season, ep_str, scraper, player, quality, download, info_only):
    """Search for a show, pick one, and watch it."""
    _check_for_updates()
    tmdb = _get_tmdb()

    ep_start, ep_end = _parse_episode(ep_str) if ep_str else (None, None)

    query_str = " ".join(query) if query else None
    if not query_str:
        console.clear()
        query_str = Prompt.ask("[bold]Search for a[/bold] [cyan]TV show[/cyan]")

    if media_type == "tv":
        results = tmdb.search_tv(query_str).get("results", [])
    else:
        results = tmdb.search_movie(query_str).get("results", [])

    if not results:
        _print_info(f"No {media_type}s found for \"{query_str}\".")
        return

    title_key = "name" if media_type == "tv" else "title"
    date_key = "first_air_date" if media_type == "tv" else "release_date"
    show = _pick_with_arrows(results, title_key, date_key, "Select a show:")

    if not show:
        return

    show_name = show.get(title_key, "?")
    show_id = show["id"]

    if scraper is None and _is_anime(show):
        scraper = "anime"
        _print_info(f"Detected anime — using [bold]anime[/bold] scraper")

    if season is not None and ep_start is not None:
        _play_with_menu(show, season, ep_start, ep_end, f"S{season:02d}E{ep_start:02d}", scraper, player, quality, info_only, download)
        return

    theme = get_theme()
    console.clear()
    console.print(Panel(f"[bold {theme['accent']}]{show_name}[/bold {theme['accent']}]", border_style=theme["border"]))

    if media_type == "tv":
        _interactive_episode_picker(tmdb, show, scraper, player, quality, info_only, download, ep_start, ep_end)
    else:
        _print_info("Movie playback not yet implemented. Stay tuned.")


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--query", help="Search query (omit for interactive)")
@click.option("--id", "tv_id", type=int, help="TMDB show ID")
@click.option("-s", "--season", type=int, help="Season number")
@click.option("-e", "--episode", "ep_str", help="Episode number or range (e.g. 1 or 1-10)")
@click.option("--scraper", help="Scraper name")
@click.option("--player", help="Player: vlc, mpv, or auto")
@click.option("-d", "--download", is_flag=True, help="Download instead of streaming")
@click.option("--info-only", is_flag=True, help="Show the m3u8 URL without playing")
@click.option("-q", "--quality", help="Video quality: 480p, 720p, 1080p, best, worst")
@_handle_tmdb_error
def watch(query, tv_id, season, ep_str, scraper, player, download, info_only, quality):
    """Browse episodes interactively and play one."""
    _check_for_updates()
    tmdb = _get_tmdb()

    ep_start, ep_end = _parse_episode(ep_str) if ep_str else (None, None)

    if tv_id:
        show = tmdb.get_tv_details(tv_id)
        show_name = show.get("name", "?")
        console.print(f"  [bold]{show_name}[/bold]")
        if scraper is None and _is_anime(show):
            scraper = "anime"
            _print_info(f"Detected anime — using [bold]anime[/bold] scraper")
        if season is not None and ep_start is not None:
            _play_with_menu(show, season, ep_start, ep_end, f"E{ep_start}", scraper, player, quality, info_only, download)
            return
    elif query:
        results = tmdb.search_tv(query).get("results", [])
        show = _pick_with_arrows(results, "name", "first_air_date", "Select a show:")
        if not show:
            return
    else:
        query = Prompt.ask("Search for a show")
        results = tmdb.search_tv(query).get("results", [])
        show = _pick_with_arrows(results, "name", "first_air_date", "Select a show:")
        if not show:
            return

    if scraper is None and _is_anime(show):
        scraper = "anime"
        _print_info(f"Detected anime — using [bold]anime[/bold] scraper")
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
            season_chosen = questionary.select("Select a season:", choices=season_choices).unsafe_ask()
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
        ep_chosen = questionary.select(
            f"Season {season_num} - Select an episode:",
            choices=ep_choices,
        ).unsafe_ask()
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
    table.add_column("Quality", style="yellow")
    table.add_column("Progress", style="green")

    for i, d in enumerate(dls, 1):
        table.add_row(str(i), d.get("title", "?"), d.get("quality", "-"), "[yellow]interrupted[/yellow]")

    console.print(table)

    choice = Prompt.ask("Resume which download?", default="1")
    try:
        d = dls[int(choice) - 1]
    except (ValueError, IndexError):
        return

    track_id = d["id"]
    url = d.get("url")
    title = d.get("title", "video")
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
    table.add_column("Quality", style="yellow")
    table.add_column("Status")
    table.add_column("Date")

    for d in all_dls:
        table.add_row(
            d.get("id", "?"),
            d.get("title", "?"),
            d.get("quality", "-"),
            d.get("status", "?"),
            d.get("timestamp", ""),
        )

    console.print(table)

    if Prompt.ask("Clear completed/interrupted?", default="n").strip().lower() in ("y", "yes"):
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
def tui():
    """Launch the full-screen TUI."""
    from .tui import run_tui
    run_tui()


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
    console.clear()
    theme = get_theme()
    console.print(Panel(f"[bold {theme['accent']}]{show_name}[/bold {theme['accent']}]", border_style=theme["border"]))

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
                season = questionary.select("Select a season:", choices=[
                    questionary.Choice(title=f"Season {s}", value=s) for s in season_keys
                ]).unsafe_ask()
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
            tt = questionary.select("Translation:", choices=[
                questionary.Choice(title=k, value=k) for k in tt_keys
            ], default="sub").unsafe_ask()
        except Exception:
            tt = "sub"
    else:
        tt = tt_keys[0]
        if tt != "sub":
            console.print(f"  [dim]Using {tt}[/dim]")

    episodes = season_data[tt]
    max_ep = max(episodes)
    ep_start, ep_end = _parse_episode(ep_str) if ep_str else (None, None)

    if ep_start is not None:
        if ep_start not in episodes:
            _print_error(f"Episode {ep_start} not found (available: 1-{max_ep}).")
            return
        if ep_end is not None and ep_end > max_ep:
            ep_end = max_ep
    else:
        try:
            ep_choices = [questionary.Choice(title=f"Episode {e}", value=e) for e in sorted(episodes)]
            ep_chosen = questionary.select("Select an episode:", choices=ep_choices).unsafe_ask()
            if not ep_chosen:
                return
            ep_start = ep_chosen
        except Exception:
            ep_start = Prompt.ask("Episode", default="1")
            try:
                ep_start = int(ep_start)
            except ValueError:
                _print_error("Invalid episode number.")
                return

    if scraper is None:
        scraper = "anime"

    show_dict = {"name": show_name, "id": 0}
    ep_name = f"S{season:02d}E{ep_start:02d}"
    _play_with_menu(show_dict, season, ep_start, ep_end, ep_name, scraper, player, quality, info_only, download)


@cli.command()
def update():
    """Check for and install the latest version of cinnamon from GitHub."""
    import requests

    theme = get_theme()

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{_UPDATE_REPO}/tags",
            timeout=5,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code != 200:
            _print_error("Could not check for updates from GitHub.")
            return
        tags = resp.json()
        if not tags:
            _print_error("No tags found on GitHub.")
            return
        latest = tags[0].get("name", "").lstrip("v")
        if not latest:
            _print_error("Could not determine latest version.")
            return
    except Exception as e:
        _print_error("Failed to check for updates.", str(e))
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
            _print_success(f"Updated to {latest}!")
        else:
            _print_error(f"Update failed (exit code {proc.returncode}).")
    except Exception as e:
        _print_error("Update failed.", str(e))


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
