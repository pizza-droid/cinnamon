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
            if _in_termux():
                # Running the absolute Termux path (e.g. /data/data/com.termux/...)
                # can fail with Exec format error; invoke via PATH name instead.
                return name
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
            if _in_termux():
                return name
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


def _termux_ensure_mpv_conf():
    """Create mpv-android's config so English audio + subtitles are on by default.

    mpv-android (Termux) does not accept CLI flags via the VIEW intent, so the
    only reliable way to make subtitles show automatically is its mpv.conf.
    True pixel-burn-in is not possible for live HLS playback; auto-selecting
    the English subtitle track is the practical equivalent.
    """
    try:
        home = os.path.expanduser("~")
        conf_dir = os.path.join(home, ".config", "mpv")
        os.makedirs(conf_dir, exist_ok=True)
        conf_path = os.path.join(conf_dir, "mpv.conf")
        desired = "alang=eng\nslang=eng\nsub-auto=all\n"
        if os.path.isfile(conf_path):
            with open(conf_path, "r", encoding="utf-8") as f:
                existing = f.read()
            if "slang=eng" in existing and "sub-auto=all" in existing:
                return
            with open(conf_path, "a", encoding="utf-8") as f:
                f.write("\n" + desired)
        else:
            with open(conf_path, "w", encoding="utf-8") as f:
                f.write(desired)
    except OSError:
        pass


def _termux_open(url, app, referer=None, user_agent=None):
    """Launch an Android media app via an explicit `am start` VIEW intent.

    On Termux, mpv/vlc are Android apps, not CLI binaries. Relying on the
    pkg wrapper scripts is unreliable (VLC in particular never opens), so we
    invoke the activity manager directly.

    When a referer (or custom UA) is required, the URL is served through a
    tiny local proxy that injects those headers — many direct hosts
    (e.g. mp4upload) block hotlinked requests that lack the Referer, which
    would otherwise make the Android player fail to open the file.
    """
    components = {
        "mpv": "is.xyz.mpv/.MPVActivity",
        "vlc": "org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity",
    }
    comp = components.get(app)
    if not comp:
        raise PlayerLaunchError(app, f"Unknown Termux app: {app}")
    if app == "mpv":
        _termux_ensure_mpv_conf()

    if referer or user_agent:
        url = _termux_proxy_url(url, referer, user_agent)

    cmd = f'am start --user 0 -a android.intent.action.VIEW -d "{url}" -n {comp}'
    try:
        return subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise PlayerLaunchError(app, str(e))


def _termux_proxy_url(target_url, referer=None, user_agent=None):
    """Start a local HTTP proxy that forwards to target_url with injected
    headers, and return the local URL to hand to the Android player."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import urllib.request

    _PROXY_HEADERS = {}
    if referer:
        _PROXY_HEADERS["Referer"] = referer
    if user_agent:
        _PROXY_HEADERS["User-Agent"] = user_agent

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                req = urllib.request.Request(target_url, headers=_PROXY_HEADERS)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    self.send_response(resp.status)
                    length = resp.headers.get("Content-Length")
                    ctype = resp.headers.get("Content-Type", "application/octet-stream")
                    self.send_header("Content-Type", ctype)
                    if length:
                        self.send_header("Content-Length", length)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            break
            except Exception:
                try:
                    self.send_error(502)
                except Exception:
                    pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/video.mp4"


def _launch(player_name, cmd):
    """Launch a desktop player and verify it actually started.

    If the process exits within a short grace period (e.g. no $DISPLAY on a
    headless/WSL box, or missing libs), capture its stderr and raise a clear
    PlayerLaunchError instead of returning a dead process that the caller then
    blocks on forever."""
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
    except OSError as e:
        hint = (
            f" — try reinstalling with: pkg install {player_name}"
            if "Exec format" in str(e) or "No such file" in str(e)
            else ""
        )
        raise PlayerLaunchError(player_name, str(e) + hint)

    # Give the player a moment to fail (missing display, codec, etc.).
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        # Still alive after 3s — it started successfully. Detach stderr.
        if proc.poll() is not None:
            # Exited in the gap between the timeout firing and us checking.
            pass
        elif proc.stderr and not proc.stderr.closed:
            try:
                proc.stderr.close()
            except OSError:
                pass
        return proc

    # Exited during the grace period: it failed to start.
    err = ""
    try:
        if proc.stderr:
            err = proc.stderr.read().decode("utf-8", "replace").strip()
    except (OSError, ValueError):
        pass
    msg = f"{player_name} exited immediately"
    if "DISPLAY" in err or "display" in err.lower() or "X11" in err or "Wayland" in err:
        msg += " — no display found. Set $DISPLAY (e.g. an X server on :0) or run from a desktop session."
    elif err:
        msg += f": {err[:300]}"
    else:
        msg += " — the stream could not be loaded (source may be down or blocked). Try another scraper, quality, or title."
    raise PlayerLaunchError(player_name, msg)


def play_vlc(url, title="", referer=None):
    exe = _vlc_path()
    if not exe:
        raise PlayerNotFoundError("vlc")
    if _in_termux():
        return _termux_open(url, "vlc", referer=referer, user_agent=DEFAULT_UA)
    cmd = [exe, "--play-and-exit", f"--meta-title={title}"]
    if referer:
        cmd.append(f"--http-referrer={referer}")
    cmd.append(url)
    return _launch("VLC", cmd)


def play_mpv(url, title="", referer=None):
    exe = _mpv_path()
    if not exe:
        raise PlayerNotFoundError("mpv")
    if _in_termux():
        return _termux_open(url, "mpv", referer=referer, user_agent=DEFAULT_UA)
    cmd = [exe, f"--title={title}", "--alang=eng", "--slang=eng", "--subs-with-matching-audio=yes",
           "--cache=yes", "--cache-secs=300", "--ytdl=no",
           "--network-timeout=20", "--keep-open=no"]
    if referer:
        cmd += ["--http-header-fields=Referer: " + referer]
    cmd.append(url)
    return _launch("mpv", cmd)


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

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    import re
    last_pct = -1
    try:
        for line in proc.stdout:
            if "[download]" not in line:
                continue
            m = re.search(r"(\d+\.?\d*)%\s+of\s+~?\s*([\d.]+)(\w+).*ETA\s+(\S+)", line)
            if not m:
                m = re.search(r"(\d+\.?\d*)%\s+of\s+~?\s*([\d.]+)(\w+)", line)
            if m:
                pct = float(m.group(1))
                if int(pct) == last_pct:
                    continue
                last_pct = int(pct)
                size_val = float(m.group(2))
                unit = m.group(3)
                eta = m.group(4) if m.lastindex >= 4 else ""
                bar_width = 25
                filled = int(bar_width * pct / 100)
                bar = "█" * filled + "░" * (bar_width - filled)
                eta_str = f" ETA {eta}" if eta else ""
                print(f"\r  {bar}  {pct:>5.1f}%  {size_val:.1f}{unit}{eta_str}    ", end="", file=sys.stderr, flush=True)
            else:
                print(f"\r  {line.rstrip():<50}", file=sys.stderr, flush=True)

        proc.wait()
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
        mpv = _mpv_path()
        vlc = _vlc_path()
        if mpv:
            try:
                return play_mpv(url, title, referer)
            except PlayerLaunchError:
                if not vlc:
                    raise
        if vlc:
            return play_vlc(url, title, referer)
        raise PlayerNotFoundError("auto")
    if player == "vlc":
        return play_vlc(url, title, referer)
    if player == "mpv":
        return play_mpv(url, title, referer)
    raise ValueError(f"Unknown player: {player}. Use vlc, mpv, or auto.")
