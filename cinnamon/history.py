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
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        entries = []
        for title, entry in data.items():
            entry["title"] = title
            entries.append(entry)
        _save(entries)
        return entries
    return data


def _save(h):
    with open(_db(), "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)


def set_history(title, season, episode, scraper=None, translation=None, quality=None):
    from .config import load_config
    if not load_config().get("history_enabled", True):
        return
    h = _load()
    h.append({
        "title": title,
        "season": season,
        "episode": episode,
        "timestamp": time.time(),
        "scraper": scraper,
        "translation": translation,
        "quality": quality,
    })
    _save(h)


def get_history(title):
    h = _load()
    return [e for e in h if e.get("title") == title]


def list_history():
    h = _load()
    return sorted(h, key=lambda e: e.get("timestamp", 0), reverse=True)


def clear_history(title=None):
    h = _load()
    if title:
        h = [e for e in h if e.get("title") != title]
    else:
        h = []
    _save(h)