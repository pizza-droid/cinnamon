import importlib
import inspect
import os
import sys
from pathlib import Path

from .base import BaseScraper
from .example import ExampleScraper
from .vidsrc import VidSrcScraper
from .torrentio import TorrentioScraper
from .webstream import WebStreamScraper
from .anime import AnimeScraper

_BUILTIN_SCRAPERS = [ExampleScraper, VidSrcScraper, TorrentioScraper, WebStreamScraper, AnimeScraper]


def _discover_user_scrapers(scrapers_dir):
    discovered = []
    if not scrapers_dir or not os.path.isdir(scrapers_dir):
        return discovered

    sys.path.insert(0, str(scrapers_dir))
    try:
        for f in sorted(os.listdir(scrapers_dir)):
            if f.endswith(".py") and f != "__init__.py":
                mod_name = f[:-3]
                try:
                    mod = importlib.import_module(mod_name)
                    for name, obj in inspect.getmembers(mod, inspect.isclass):
                        if (
                            issubclass(obj, BaseScraper)
                            and obj is not BaseScraper
                            and obj not in _BUILTIN_SCRAPERS
                        ):
                            discovered.append(obj)
                except Exception:
                    pass
    finally:
        if sys.path and sys.path[0] == str(scrapers_dir):
            sys.path.pop(0)

    return discovered


def _get_all_scraper_classes():
    from ..config import SCRAPERS_DIR

    classes = list(_BUILTIN_SCRAPERS)
    classes.extend(_discover_user_scrapers(SCRAPERS_DIR))

    custom_path = os.getenv("CINNAMON_SCRAPERS_PATH")
    if custom_path:
        classes.extend(_discover_user_scrapers(custom_path))

    seen = set()
    unique = []
    for cls in classes:
        if cls.name not in seen:
            seen.add(cls.name)
            unique.append(cls)
    return unique


def get_scraper(name):
    for cls in _get_all_scraper_classes():
        if cls.name == name:
            return cls()
    return None


def list_scrapers():
    return [
        {"name": cls.name, "description": cls.description, "builtin": cls in _BUILTIN_SCRAPERS}
        for cls in _get_all_scraper_classes()
    ]
