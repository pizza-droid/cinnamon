import json
import os
import shutil
import subprocess
import sys
import time

from .errors import PlayerNotFoundError, PlayerLaunchError


def _in_termux():
    return bool(os.environ.get("TERMUX_VERSION")) or os.path.isdir("/data/data/com.termux")


def _platform_os():
    if _in_termux():
        return "termux"
    return sys.platform


def _platform_ua():
    if _platform_os() == "win32":
        return "Windows NT 10.0; Win64; x64"
    if _platform_os() == "darwin":
        return "Macintosh; Intel Mac OS X 10_15_7"
    if _platform_os() == "termux":
        return "Linux; Android 10; Termux"
    return "X11; Linux x86_64"


DEFAULT_UA = f"Mozilla/5.0 ({_platform_ua()}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"


def _search_path(names):
    for name in names:
        path = shutil.which(name)
        if path:
            return path

    common = []

    if _platform_os() == "win32":
        common += [
            r"C:\Program Files\mpv\mpv.exe",
            r"C:\Tools\mpv\mpv.exe",
            os.path.expandvars(r"%USERPROFILE%\scoop\apps\mpv\current\mpv.exe"),
            os.path.expandvars(r"%USERPROFILE%\mpv\mpv.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\mpv\mpv.exe"),
            os.path.expandvars(r"%HOMEDRIVE%%HOMEPATH%\mpv\mpv.exe"),
            os.path.expandvars(r"%ProgramFiles%\VideoLAN\VLC\vlc.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\VideoLAN\VLC\vlc.exe"),
        ]
    elif _platform_os() == "darwin":
        home = os.path.expanduser("~")
        common += [
            "/Applications/VLC.app/Contents/MacOS/VLC",
            "/usr/local/bin/mpv",
            "/usr/local/bin/vlc",
            "/opt/homebrew/bin/mpv",
            "/opt/homebrew/bin/vlc",
            "/opt/homebrew/bin/yt-dlp",
            os.path.join(home, "homebrew", "bin", "mpv"),
            os.path.join(home, "homebrew", "bin", "vlc"),
            os.path.join(home, "homebrew", "bin", "yt-dlp"),
        ]
    elif _platform_os() == "termux":
        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        common += [
            os.path.join(prefix, "bin", "mpv"),
            os.path.join(prefix, "bin", "vlc"),
            os.path.join(prefix, "bin", "yt-dlp"),
        ]
    else:
        common += [
            "/usr/bin/mpv",
            "/usr/bin/vlc",
            "/usr/bin/yt-dlp",
            "/usr/local/bin/mpv",
            "/usr/local/bin/vlc",
            "/usr/local/bin/yt-dlp",
            "/snap/bin/mpv",
            "/snap/bin/vlc",
        ]

    for candidate in common:
        if os.path.isfile(candidate):
            return candidate
    return None


def _vlc_path():
    return _search_path(["vlc.exe", "vlc"])


def _mpv_path():
    return _search_path(["mpv.exe", "mpv"])


def _ytdlp_path():
    for name in ("yt-dlp.exe", "yt-dlp"):
        path = shutil.which(name)
        if path:
            return path

    candidates = []
    if _platform_os() == "win32":
        candidates = [
            os.path.expandvars(r"%USERPROFILE%\scoop\apps\yt-dlp\current\yt-dlp.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\yt-dlp\yt-dlp.exe"),
        ]
    elif _platform_os() == "darwin":
        candidates = [
            "/opt/homebrew/bin/yt-dlp",
            "/usr/local/bin/yt-dlp",
        ]
    elif _platform_os() == "termux":
        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        candidates = [os.path.join(prefix, "bin", "yt-dlp")]
    else:
        candidates = [
            "/usr/bin/yt-dlp",
            "/usr/local/bin/yt-dlp",
            "/snap/bin/yt-dlp",
        ]

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def ytdlp_install_hint():
    if _platform_os() == "win32":
        return "scoop install yt-dlp"
    if _platform_os() == "darwin":
        return "brew install yt-dlp"
    if _platform_os() == "termux":
        return "pkg install yt-dlp"
    return "pip install yt-dlp"


def play_vlc(url, title="", referer=None):
    exe = _vlc_path()
    if not exe:
        raise PlayerNotFoundError("vlc")
    cmd = [exe, "--play-and-exit", f"--meta-title={title}"]
    if referer:
        cmd.append(f"--http-referrer={referer}")
    cmd.append(url)
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise PlayerLaunchError("VLC", str(e))


def play_mpv(url, title="", referer=None):
    exe = _mpv_path()
    if not exe:
        raise PlayerNotFoundError("mpv")
    cmd = [exe, f"--title={title}", "--alang=eng", "--slang=eng", "--subs-with-matching-audio=yes"]
    if referer:
        cmd += ["--http-header-fields=Referer: " + referer]
    cmd.append(url)
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise PlayerLaunchError("mpv", str(e))


def _streamer_path():
    return os.path.join(os.path.dirname(__file__), "webtorrent_stream.mjs")


def _play_magnet(url, title="", player="auto", season=None, episode=None):
    mpv = _mpv_path()
    vlc = _vlc_path()

    if player == "mpv":
        if not mpv:
            raise PlayerNotFoundError("mpv")
        player_fn = lambda u: play_mpv(u, title)
        exe_dir = os.path.dirname(mpv)
    elif player == "vlc":
        if not vlc:
            raise PlayerNotFoundError("vlc")
        player_fn = lambda u: play_vlc(u, title)
        exe_dir = os.path.dirname(vlc)
    elif player == "auto":
        if mpv:
            player_fn = lambda u: play_mpv(u, title)
            exe_dir = os.path.dirname(mpv)
        elif vlc:
            player_fn = lambda u: play_vlc(u, title)
            exe_dir = os.path.dirname(vlc)
        else:
            raise PlayerNotFoundError("auto")
    else:
        raise ValueError(f"Unknown player: {player}")

    env = os.environ.copy()
    env["PATH"] = exe_dir + os.pathsep + env["PATH"]

    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        raise PlayerNotFoundError("node")

    port = 8888
    args = [node, _streamer_path(), url, str(port)]
    if season is not None:
        args.append(str(season))
    if episode is not None:
        args.append(str(episode))

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, text=True, env=env,
    )

    stream_url = None
    deadline = time.monotonic() + 60

    try:
        for line in proc.stdout:
            if time.monotonic() > deadline:
                proc.kill()
                raise PlayerLaunchError("streamer", "Timed out waiting for stream URL")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            status = msg.get("status")
            if status == "dht_bootstrapping":
                print("  DHT bootstrapping...", file=sys.stderr)
            elif status == "dht_ready":
                print(f"  DHT ready ({msg.get('nodes', 0)} nodes)", file=sys.stderr)
            elif status == "adding_torrent":
                print("  Adding torrent...", file=sys.stderr)
            elif status == "metadata":
                print(f"  Torrent: {msg.get('name')}", file=sys.stderr)
                print(f"  Files: {msg.get('numFiles')}", file=sys.stderr)
                print(f"  Selected: {msg.get('selectedFile')}", file=sys.stderr)
            elif status == "ready":
                stream_url = msg.get("streamUrl")
                port = msg.get("port")
                file_name = msg.get("file")
                had_peer = msg.get("hadPeer")
                print(f"  Streaming: {file_name}", file=sys.stderr)
                print(f"  URL: {stream_url}", file=sys.stderr)
                if not had_peer:
                    print("  Waiting for peers...", file=sys.stderr)
                break
            elif status == "progress":
                downloaded = msg.get("downloaded", 0)
                num_peers = msg.get("numPeers", 0)
                print(f"  Progress: {msg.get('progress', 0)*100:.0f}%  ({downloaded//1048576} MB) peers: {num_peers}", file=sys.stderr)
            elif msg.get("type") == "warn":
                print(f"  Warn: {msg.get('msg')}", file=sys.stderr)
            elif msg.get("type") == "error":
                print(f"  Error: {msg.get('msg')}", file=sys.stderr)

        if not stream_url:
            proc.kill()
            proc.wait()
            raise PlayerLaunchError(
                "streamer",
                "No peers found for this torrent. The source may have no seeders right now.\n"
                "  Try again later, pick a different episode, or use --scraper vidsrc for HTTP streaming."
            )

        player_fn(stream_url)

        # Keep reading progress lines until the player exits (or streamer dies)
        for line in proc.stdout:
            try:
                msg = json.loads(line.strip())
            except (json.JSONDecodeError, AttributeError):
                continue
            if msg.get("status") == "progress":
                downloaded = msg.get("downloaded", 0)
                num_peers = msg.get("numPeers", 0)
                print(f"  Progress: {msg.get('progress', 0)*100:.0f}%  ({downloaded//1048576} MB) peers: {num_peers}", file=sys.stderr)
    except:
        try:
            proc.kill()
        except Exception:
            pass
        proc.wait()
        raise


def download_video(url, title="", referer=None, output_dir=".", track_id=None):
    """Download an HLS stream using yt-dlp with a clean progress bar."""
    from .downloads import update as _track_update

    exe = _ytdlp_path()
    if not exe:
        raise PlayerNotFoundError("yt-dlp")

    safe = "".join(c if c.isalnum() or c in " .-_()" else "_" for c in title) or "video"
    outtmpl = os.path.join(output_dir, f"{safe}.%(ext)s")

    cmd = [exe, "--no-mtime", "--no-warnings", "-o", outtmpl]
    if referer:
        cmd += ["--referer", referer]
    cmd.append(url)

    if track_id:
        _track_update(track_id, status="downloading")

    print(f"Downloading to {os.path.abspath(output_dir)}", file=sys.stderr)

    import threading

    spinner_stop = threading.Event()
    def _spin():
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not spinner_stop.is_set():
            print(f"\r  {chars[i % len(chars)]} Downloading...   ", end="", file=sys.stderr)
            i += 1
            spinner_stop.wait(0.1)
    spinner_thread = threading.Thread(target=_spin, daemon=True)

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )

    spinner_thread.start()
    last_pct = -1
    try:
        for line in proc.stderr:
            if "[download]" not in line:
                continue

            import re
            m = re.search(r"(\d+\.?\d*)%\s+of\s+~?\s*([\d.]+)(\w+).*ETA\s+(\S+)", line)
            if not m:
                m = re.search(r"(\d+\.?\d*)%\s+of\s+~?\s*([\d.]+)(\w+)", line)

            if m:
                spinner_stop.set()
                pct = float(m.group(1))
                size_val = float(m.group(2))
                unit = m.group(3)
                eta = m.group(4) if m.lastindex >= 4 else ""

                if int(pct) != last_pct:
                    last_pct = int(pct)
                    bar_width = 25
                    filled = int(bar_width * pct / 100)
                    bar = "█" * filled + "░" * (bar_width - filled)
                    eta_str = f" ETA {eta}" if eta else ""
                    print(f"\r  {bar}  {pct:>5.1f}%  {size_val:.1f}{unit}{eta_str}", end="", file=sys.stderr)

        proc.wait()
        spinner_stop.set()
        spinner_thread.join(1)
        print(file=sys.stderr)

        if proc.returncode == 0:
            if track_id:
                _track_update(track_id, status="completed")
            print(f"  Done — {safe}", file=sys.stderr)
        else:
            raise PlayerLaunchError("yt-dlp", f"exit code {proc.returncode}")

    except KeyboardInterrupt:
        print(file=sys.stderr)
        if track_id:
            _track_update(track_id, status="interrupted")
        proc.kill()
        proc.wait()
        raise
    except PlayerLaunchError:
        if track_id:
            _track_update(track_id, status="error")
        raise


def play(url, title="", player="auto", season=None, episode=None, referer=None):
    if url.startswith("magnet:"):
        return _play_magnet(url, title, player, season, episode)
    if player == "auto":
        if _mpv_path():
            return play_mpv(url, title, referer)
        if _vlc_path():
            return play_vlc(url, title, referer)
        raise PlayerNotFoundError("auto")
    if player == "vlc":
        return play_vlc(url, title, referer)
    if player == "mpv":
        return play_mpv(url, title, referer)
    raise ValueError(f"Unknown player: {player}. Use vlc, mpv, or auto.")
