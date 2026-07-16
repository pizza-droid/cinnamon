from __future__ import annotations

import asyncio

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Static,
)

from .config import load_config
from .errors import PlayerNotFoundError, ScraperError, TMDBNotFoundError
from .player import play
from .scrapers import get_scraper
from .tmdb import TMDBClient

# ---------------------------------------------------------------------------
# CSS — opencode-inspired dark theme
# ---------------------------------------------------------------------------

CSS = """
Screen {
    background: #0f0f1a;
}

Header {
    background: #1a1a2e;
    color: #7ec8e3;
    text-style: bold;
}

Footer {
    background: #1a1a2e;
    color: #555577;
}

Footer > .footer--key {
    color: #7ec8e3;
    text-style: bold;
}

Footer > .footer--description {
    color: #555577;
}

#search-input {
    background: #1a1a2e;
    color: #e0e0f0;
    border: tall #2a2a4e;
    padding: 0 2;
    margin: 1 2 0 2;
}

#search-input:focus {
    border: tall #7ec8e3;
}

#results-list {
    background: #0f0f1a;
    border: none;
    margin: 0 2;
}

#results-list:focus {
    border: none;
}

#results-list > ListItem {
    background: #0f0f1a;
    padding: 1 2;
    margin: 0 0 1 0;
}

#results-list > ListItem:hover {
    background: #1a1a3e;
}

#results-list > ListItem.--highlighted {
    background: #1a2a4e;
}

#results-list > ListItem.--highlighted > Label {
    color: #e0e0f0;
}

#results-hint {
    height: 1;
    margin: 0 2;
}

#results-hint Label {
    color: #444466;
}

/* ── show header ─────────────────────────────────── */

#show-header {
    background: #1a1a2e;
    height: 3;
    margin: 1 2 0 2;
}

#show-title {
    color: #e0e0f0;
    text-style: bold;
    padding: 1 2;
    width: 1fr;
}

#show-year {
    color: #555577;
    padding: 1 2;
    width: auto;
}

/* ── season bar ──────────────────────────────────── */

#season-bar {
    background: #0f0f1a;
    height: 3;
    margin: 0 2;
}

#season-bar Button {
    background: #2a2a4e;
    color: #8888aa;
    border: none;
    margin: 1 1 1 0;
    padding: 0 2;
}

#season-bar Button:focus {
    background: #3a3a6e;
    color: #e0e0f0;
}

#season-bar Button.-active {
    background: #7ec8e3;
    color: #0f0f1a;
    text-style: bold;
}

/* ── episode list ────────────────────────────────── */

#episode-list {
    background: #0f0f1a;
    border: none;
    margin: 0 2;
}

#episode-list > ListItem {
    background: #0f0f1a;
    padding: 1 2;
    margin: 0 0 1 0;
}

#episode-list > ListItem:hover {
    background: #1a1a3e;
}

#episode-list > ListItem.--highlighted {
    background: #1a2a4e;
}

#episode-list > ListItem.--highlighted > Label {
    color: #e0e0f0;
}

/* ── feedback panels ─────────────────────────────── */

Static.error {
    color: #ff6b6b;
    background: #2a1a1a;
    padding: 1 2;
    margin: 1 2;
    border: tall #ff6b6b;
}

Static.success {
    color: #69db7c;
    padding: 1 2;
    margin: 1 2;
    border: tall #69db7c;
}

Static.info {
    color: #7ec8e3;
    padding: 1 2;
    margin: 1 2;
    border: tall #2a2a4e;
}

LoadingIndicator {
    background: #0f0f1a;
    color: #7ec8e3;
}
"""

# ---------------------------------------------------------------------------
# TMDB helpers (called from workers)
# ---------------------------------------------------------------------------


def _search_tmdb(query: str) -> list[dict]:
    try:
        return TMDBClient().search_tv(query).get("results", [])
    except Exception:
        return []


def _get_show_details(show_id: int) -> dict:
    try:
        return TMDBClient().get_tv_details(show_id)
    except Exception:
        return {}


def _get_episodes(show_id: int, season: int) -> list[dict]:
    try:
        data = TMDBClient().get_season_details(show_id, season)
        return data.get("episodes", [])
    except Exception:
        return []


def _resolve(show: str, show_id: int, season: int, episode: int) -> tuple[str, str]:
    cfg = load_config()
    name = cfg.get("default_scraper", "example")
    s = get_scraper(name)
    if not s:
        return "", ""
    try:
        r = s.resolve({"show": show, "tv_id": show_id, "season": season, "episode": episode})
        if r:
            return r.m3u8_url, r.title
    except ScraperError:
        pass
    return "", ""


# ---------------------------------------------------------------------------
# Search screen
# ---------------------------------------------------------------------------


class SearchScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
        Binding("ctrl+c", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="Search for a TV show ...", id="search-input")
        yield Horizontal(
            Label("type to search  |  arrow keys to navigate  |  enter to select", id="results-hint"),
        )
        yield ListView(id="results-list")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    @on(Input.Changed, "#search-input")
    async def on_search(self, event: Input.Changed) -> None:
        q = event.value.strip()
        lst = self.query_one("#results-list", ListView)
        lst.clear()
        if len(q) < 2:
            return
        lst.loading = True
        worker = self.run_worker(lambda: _search_tmdb(q), name="tmdb-search", thread=True)
        results = await worker.wait()
        lst.loading = False
        if not results:
            lst.append(ListItem(Label("[dim]No results[/dim]")))
            return
        for s in results[:20]:
            name = s.get("name", "?")
            year = (s.get("first_air_date") or "?")[:4]
            lst.append(ListItem(Label(f"{name}  [dim]({year})[/dim]")))
        lst.index = 0

    @on(ListView.Selected, "#results-list")
    def on_select(self, event: ListView.Selected) -> None:
        idx = self.query_one("#results-list", ListView).index
        if idx is None:
            return
        results = self._last_results()
        if idx < len(results):
            show = results[idx]
            self.app.push_screen(EpisodeScreen(show["id"], show.get("name", "?")))

    def _last_results(self) -> list[dict]:
        input_w = self.query_one("#search-input", Input)
        q = input_w.value.strip()
        if len(q) >= 2:
            return _search_tmdb(q)
        return []


# ---------------------------------------------------------------------------
# Episode screen
# ---------------------------------------------------------------------------


class EpisodeScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("ctrl+c", "app.quit", "Quit"),
        Binding("left", "prev_season", "◀ Season"),
        Binding("right", "next_season", "Season ▶"),
    ]

    def __init__(self, show_id: int, show_name: str) -> None:
        super().__init__()
        self.show_id = show_id
        self.show_name = show_name
        self.seasons: list[int] = []
        self.current_season = 1

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Horizontal(
            Label(self.show_name, id="show-title"),
            Label("", id="show-year"),
            id="show-header",
        )
        yield Horizontal(id="season-bar")
        yield ListView(id="episode-list")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        details = _get_show_details(self.show_id)
        total = details.get("number_of_seasons", 0)
        year = (details.get("first_air_date") or "")[:4]
        if year:
            try:
                self.query_one("#show-year", Label).update(year)
            except NoMatches:
                pass
        if total < 1:
            self._episode_error("No season data for this show.")
            return
        self.seasons = list(range(1, total + 1))
        self.current_season = 1
        self._build_seasons()
        self._load(self.current_season)

    def _build_seasons(self) -> None:
        try:
            bar = self.query_one("#season-bar", Horizontal)
        except NoMatches:
            return
        bar.remove_children()
        for s in self.seasons:
            btn = Button(f"S{s}", variant="default")
            btn.classes = "-active" if s == self.current_season else ""
            bar.mount(btn)
        # focus the active button
        for btn in bar.children:
            if isinstance(btn, Button) and "-active" in btn.classes:
                btn.focus()
                break

    def _load(self, season: int) -> None:
        self.current_season = season
        try:
            bar = self.query_one("#season-bar", Horizontal)
            for btn in bar.children:
                if isinstance(btn, Button):
                    btn.classes = btn.classes.replace("-active", "")
                    label = btn.label if hasattr(btn, "label") else str(btn.renderable)
                    if isinstance(label, str) and label == f"S{season}":
                        btn.classes += " -active"
        except NoMatches:
            pass

        episodes = _get_episodes(self.show_id, season)
        try:
            lst = self.query_one("#episode-list", ListView)
        except NoMatches:
            return

        lst.clear()
        if not episodes:
            lst.append(ListItem(Label("[dim]No episodes yet[/dim]")))
            return

        for ep in episodes:
            num = ep.get("episode_number", "?")
            name = ep.get("name", f"Episode {num}")
            date = ep.get("air_date", "")
            suffix = f"  [dim]({date})[/dim]" if date else ""
            lst.append(ListItem(Label(f"E{num:02d}  {name}{suffix}")))

        lst.index = 0
        lst.focus()

    def _episode_error(self, msg: str) -> None:
        try:
            lst = self.query_one("#episode-list", ListView)
            lst.clear()
            lst.append(ListItem(Label(f"[red]{msg}[/red]")))
        except NoMatches:
            pass

    # -- season button clicks --
    @on(Button.Pressed, "#season-bar Button")
    def on_season_press(self, event: Button.Pressed) -> None:
        label = event.button.label
        try:
            num = int(str(label).replace("S", ""))
            self._load(num)
        except (ValueError, AttributeError):
            pass

    # -- season keyboard nav --
    def action_prev_season(self) -> None:
        if self.current_season > 1:
            self._load(self.current_season - 1)

    def action_next_season(self) -> None:
        if self.current_season < len(self.seasons):
            self._load(self.current_season + 1)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    # -- episode selected --
    @on(ListView.Selected, "#episode-list")
    def on_episode_select(self, event: ListView.Selected) -> None:
        episodes = _get_episodes(self.show_id, self.current_season)
        idx = self.query_one("#episode-list", ListView).index
        if idx is None or idx >= len(episodes):
            return
        ep = episodes[idx]
        ep_num = ep.get("episode_number", 1)
        ep_name = ep.get("name", f"E{ep_num}")

        def resolve_then_play() -> str:
            url, title = _resolve(self.show_name, self.show_id, self.current_season, ep_num)
            if not url:
                return ""
            cfg = load_config()
            player = cfg.get("default_player", "auto")
            try:
                play(url, title=title, player=player, season=self.current_season, episode=ep_num)
                return f"Launched in {player.upper()}"
            except PlayerNotFoundError as e:
                return str(e)
            except Exception as e:
                return f"Error: {e}"

        self.app.push_screen(
            PlaybackScreen(self.show_name, self.current_season, ep_num, ep_name, resolve_then_play)
        )


# ---------------------------------------------------------------------------
# Playback screen (modal overlay)
# ---------------------------------------------------------------------------


class PlaybackScreen(ModalScreen):
    def __init__(self, show: str, season: int, episode: int, ep_name: str, play_fn) -> None:
        super().__init__()
        self.show = show
        self.season = season
        self.episode = episode
        self.ep_name = ep_name
        self.play_fn = play_fn

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(
                f"\n  {self.show}  S{self.season:02d}E{self.episode:02d}  -  {self.ep_name}\n",
                classes="info",
            ),
            LoadingIndicator(),
            id="box",
        )

    def on_mount(self) -> None:
        self._go()

    async def _go(self) -> None:
        worker = self.run_worker(self.play_fn, name="resolve", thread=True)
        result = await worker.wait()
        try:
            box = self.query_one("#box", Vertical)
            box.remove_children()
            if result:
                box.mount(Static(f"\n  {result}\n", classes="success"))
            else:
                box.mount(Static("\n  No stream found.\n", classes="error"))
        except NoMatches:
            pass
        await asyncio.sleep(1.5)
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class CinnamonTUI(App):
    CSS = CSS
    TITLE = "Cinnamon"
    SUB_TITLE = "TV Stream Browser"
    SCREENS = {"search": SearchScreen}

    BINDINGS = [Binding("ctrl+c", "quit", "Quit"), Binding("escape", "back_or_quit", "Back")]

    def on_mount(self) -> None:
        self.push_screen("search")

    def action_back_or_quit(self) -> None:
        if self.screen_count > 1:
            self.pop_screen()
        else:
            self.exit()


def run_tui() -> None:
    CinnamonTUI().run()
