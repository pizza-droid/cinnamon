import json
import os
import sys
import time

_DATA_DIR = None


def _data_dir():
    global _DATA_DIR
    if _DATA_DIR is None:
        if sys.platform == "win32":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
        else:
            base = os.path.join(os.path.expanduser("~"), ".local", "share")
        _DATA_DIR = os.path.join(base, "cinnamon")
        os.makedirs(_DATA_DIR, exist_ok=True)
    return _DATA_DIR


def _db():
    return os.path.join(_data_dir(), "history.json")


def _load():
    try:
        with open(_db(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(h):
    with open(_db(), "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)


def set_history(title, season, episode, scraper=None, translation=None, quality=None):
    h = _load()
    h[title] = {
        "season": season,
        "episode": episode,
        "timestamp": time.time(),
        "scraper": scraper,
        "translation": translation,
        "quality": quality,
    }
    _save(h)


def get_history(title):
    return _load().get(title)


def list_history():
    h = _load()
    return sorted(h.items(), key=lambda kv: kv[1].get("timestamp", 0), reverse=True)


def clear_history(title=None):
    h = _load()
    if title:
        h.pop(title, None)
    else:
        h.clear()
    _save(h)
