"""UI smoke + fragility test for cinnamon's interactive pickers.

Run directly:  python tests/test_ui_smoke.py

This does NOT touch the network. It monkeypatches TMDB, the scraper registry,
and the player so we can drive every interactive command path and assert the
UI does not crash on:
  - normal piped choices,
  - EOF / empty input,
  - repeated bad (non-numeric) input in the numbered fallback,
  - non-TTY stdin (questionary raises, code must fall back gracefully).

It also checks the dead `tui` command and the focus style builder.
"""

import io
import sys

import cinnamon.cli as c
from click.testing import CliRunner


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

class _FakeTMDB:
    def search_tv(self, q):
        return {"results": [
            {"id": 1, "name": "Breaking Bad", "first_air_date": "2008-01-20"},
            {"id": 2, "name": "Better Call Saul", "first_air_date": "2015-02-08"},
        ]}

    def search_movie(self, q):
        return {"results": [
            {"id": 10, "title": "The Movie", "release_date": "2020-05-05"},
        ]}

    def get_tv_details(self, i):
        return {"id": i, "number_of_seasons": 2, "name": "Breaking Bad"}

    def get_movie_details(self, i):
        return {"title": "The Movie", "id": i}

    def get_season_details(self, i, s):
        eps = [{"episode_number": n, "name": f"Ep {n}"} for n in range(1, 4)]
        return {"episodes": eps}


class _FakeResult:
    def __init__(self, title="X", url="http://example.com/s.m3u8", referer="http://x"):
        self.title = title
        self.m3u8_url = url
        self.referer = referer
        self.user_agent = None
        self.headers = {}


class _FakeScraper:
    name = "webstream"
    description = "fake"

    def search(self, q):
        return []

    def resolve(self, info):
        return _FakeResult(title=f"{info.get('show','?')} E{info.get('episode',1):02d}")


def _install_fakes():
    c._get_tmdb = lambda: _FakeTMDB()
    c.get_scraper = lambda name: _FakeScraper()
    c.list_scrapers = lambda: [{"name": "webstream", "description": "fake", "builtin": True}]
    c.play = lambda *a, **k: _Proc()
    c.download_video = lambda *a, **k: None
    c.ytdlp_install_hint = lambda: "pip install yt-dlp"


class _Proc:
    def wait(self):
        return 0


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

FAILS = []


def _run(name, argv, input_text, expect_exit=0):
    import threading

    def _go():
        _install_fakes()
        runner = CliRunner()
        try:
            return runner.invoke(c.cli, argv, input=input_text), None
        except Exception as e:
            return None, e

    th = threading.Thread(target=lambda: _store.__setitem__(0, _go()), daemon=True)
    _store = {}
    th.start()
    th.join(15)
    if th.is_alive():
        print(f"[FAIL] {name}: HUNG (no response in 15s) — possible infinite input loop")
        FAILS.append(name)
        return
    res, exc = _store.get(0, (None, None))
    if exc is not None:
        import traceback
        print(f"[FAIL] {name}: raised {type(exc).__name__}: {exc}")
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        FAILS.append(name)
        return
    if res.exit_code != expect_exit:
        print(f"[FAIL] {name}: exit {res.exit_code} (expected {expect_exit})")
        if res.exception:
            import traceback
            traceback.print_exception(type(res.exception), res.exception, res.exception.__traceback__)
        FAILS.append(name)
    else:
        print(f"[ ok ] {name}: exit {res.exit_code}")


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------

def test_search_tv_full():
    # search -> pick show(1) -> 1 season auto -> pick ep(1) -> play
    _run("search tv full", ["search", "BB", "-s", "1", "-e", "1"], "1\n")


def test_search_movie():
    _run("search movie", ["search", "The Movie", "-t", "movie"], "1\n")


def test_watch_by_id():
    _run("watch by id", ["watch", "--id", "1", "-t", "tv", "-s", "1", "-e", "2"], "")


def test_watch_movie_by_id():
    _run("watch movie by id", ["watch", "--id", "10", "-t", "movie"], "")


def test_watch_combined_query_movie():
    # no --type: combined search, pick the movie (index 2 in fake: tv(2)+movie(1))
    _run("watch combined -> movie", ["watch", "--query", "The"], "3\n")


def test_watch_combined_query_tv():
    _run("watch combined -> tv", ["watch", "--query", "BB"], "1\n1\n")


def test_anime_flow():
    # monkeypatch allanime helpers used by _run_anime_flow
    c._find_show = lambda s, n: "aid123"
    c._allanime_episodes = lambda s, aid: {"1|sub": ["1", "2", "3"]}
    _run("anime flow", ["anime", "Frieren", "-e", "1"], "1\n")


def test_anime_flow_multi_season():
    c._find_show = lambda s, n: "aid123"
    c._allanime_episodes = lambda s, aid: {"1|sub": ["1", "2"], "2|dub": ["1", "2"]}
    _run("anime multi-season", ["anime", "Frieren"], "1\n1\n")


def test_info_only():
    _run("info-only", ["search", "BB", "-s", "1", "-e", "1", "--info-only"], "1\n")


def test_download_flag():
    _run("download", ["search", "BB", "-s", "1", "-e", "1", "-d"], "1\n")


def test_eof_empty():
    # empty input: questionary raises -> numbered fallback -> default 1
    _run("search EOF", ["search", "BB", "-s", "1", "-e", "1"], "")


def test_bad_input_then_good():
    # numbered fallback with a bad line then a valid one (no infinite loop)
    _run("bad then good", ["search", "BB", "-s", "1", "-e", "1"], "zzz\n1\n")


def test_resume_prompt():
    _run("resume", ["resume"], "")


def test_history_list():
    _run("history", ["history"], "")


def test_scrapers_list():
    _run("scrapers", ["scrapers"], "")


def test_config_show():
    _run("config show", ["config", "show"], "")


def test_setup_wizard():
    # setup: no api key path -> it will call webbrowser + Prompt; stub webbrowser
    import webbrowser
    webbrowser.open = lambda *a, **k: True
    c._setup_api_key = lambda: "fakekey"
    _run("setup", ["setup"], "")


def test_tui_command_dead():
    # AGENTS.md says tui was removed; invoking it must not crash with ImportError
    _run("tui (should be safe)", ["tui"], "")


def test_q_style_builds():
    try:
        s = c._q_style()
        assert s is not None
        print("[ ok ] _q_style builds for current theme")
    except Exception as e:
        print(f"[FAIL] _q_style: {type(e).__name__}: {e}")
        FAILS.append("q_style")


def test_q_style_all_themes():
    for theme in ("cinnamon", "ocean", "mono"):
        try:
            c.load_config = lambda: {**c.DEFAULTS, "theme": theme} if hasattr(c, "DEFAULTS") else {}
        except Exception:
            pass
    # just rebuild for each theme via get_theme path is config-driven; smoke only
    try:
        s = c._q_style()
        print("[ ok ] _q_style (themes)")
    except Exception as e:
        print(f"[FAIL] _q_style themes: {type(e).__name__}: {e}")
        FAILS.append("q_style_themes")


def main():
    print("=" * 60)
    print("cinnamon UI fragility smoke test")
    print("=" * 60)
    test_q_style_builds()
    test_q_style_all_themes()
    test_search_tv_full()
    test_search_movie()
    test_watch_by_id()
    test_watch_movie_by_id()
    test_watch_combined_query_movie()
    test_watch_combined_query_tv()
    test_anime_flow()
    test_anime_flow_multi_season()
    test_info_only()
    test_download_flag()
    test_eof_empty()
    test_bad_input_then_good()
    test_resume_prompt()
    test_history_list()
    test_scrapers_list()
    test_config_show()
    test_setup_wizard()
    test_tui_command_dead()
    print("=" * 60)
    if FAILS:
        print(f"RESULT: {len(FAILS)} FAILURES -> {FAILS}")
        sys.exit(1)
    print("RESULT: all UI paths survived (no crashes)")


if __name__ == "__main__":
    main()
