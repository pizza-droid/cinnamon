import json
import os
import sys
import time
import uuid

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
    return os.path.join(_data_dir(), "downloads.json")


def _load():
    try:
        with open(_db(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(dls):
    with open(_db(), "w", encoding="utf-8") as f:
        json.dump(dls, f, indent=2, ensure_ascii=False)


def create(info):
    dls = _load()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "title": info.get("title", "Untitled"),
        "url": info.get("url"),
        "tv_id": info.get("tv_id"),
        "season": info.get("season"),
        "episode": info.get("episode"),
        "quality": info.get("quality"),
        "referer": info.get("referer"),
        "timestamp": time.time(),
        "status": "queued",
    }
    dls.append(entry)
    _save(dls)
    return entry["id"]


def update(download_id, **kwargs):
    dls = _load()
    for d in dls:
        if d["id"] == download_id:
            d.update(kwargs)
            break
    _save(dls)


def list_all(status=None):
    dls = _load()
    if status:
        return [d for d in dls if d.get("status") == status]
    return dls


def get(download_id):
    for d in _load():
        if d["id"] == download_id:
            return d
    return None


def remove(download_id):
    dls = _load()
    _save([d for d in dls if d["id"] != download_id])
