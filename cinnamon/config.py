import json
import os
from pathlib import Path

from .errors import InvalidConfig

CONFIG_DIR = Path.home() / ".config" / "cinnamon"
CONFIG_FILE = CONFIG_DIR / "config.json"
SCRAPERS_DIR = CONFIG_DIR / "scrapers"

DEFAULTS = {
    "tmdb_api_key": "",
    "default_scraper": "webstream",
    "default_player": "auto",
    "theme": "cinnamon",
    "scrapers": {},
}


THEMES = {
    "cinnamon": {
        "accent": "orange1",
        "accent2": "gold1",
        "success": "green",
        "error": "red",
        "info": "cyan",
        "dim": "grey50",
        "panel": "bright_yellow",
        "border": "orange1",
    },
    "ocean": {
        "accent": "deep_sky_blue1",
        "accent2": "cyan",
        "success": "spring_green2",
        "error": "red",
        "info": "light_cyan1",
        "dim": "grey50",
        "panel": "deep_sky_blue1",
        "border": "blue",
    },
    "mono": {
        "accent": "white",
        "accent2": "bright_white",
        "success": "green",
        "error": "red",
        "info": "bright_white",
        "dim": "grey35",
        "panel": "bright_white",
        "border": "grey50",
    },
}


def get_theme():
    cfg = load_config()
    name = cfg.get("theme", "cinnamon")
    return THEMES.get(name, THEMES["cinnamon"])


def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return {**DEFAULTS, **data}
        except (json.JSONDecodeError, OSError) as e:
            raise InvalidConfig(str(e))
    return dict(DEFAULTS)


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    merged = {**DEFAULTS, **config}
    CONFIG_FILE.write_text(json.dumps(merged, indent=2))


def get_tmdb_api_key():
    api_key = os.getenv("TMDB_API_KEY")
    if api_key:
        return api_key
    return load_config().get("tmdb_api_key", "")


def set_tmdb_api_key(api_key):
    config = load_config()
    config["tmdb_api_key"] = api_key
    save_config(config)


def get_scraper_config(scraper_name):
    config = load_config()
    return config.get("scrapers", {}).get(scraper_name, {})


def set_scraper_config(scraper_name, key, value):
    config = load_config()
    if "scrapers" not in config:
        config["scrapers"] = {}
    if scraper_name not in config["scrapers"]:
        config["scrapers"][scraper_name] = {}
    config["scrapers"][scraper_name][key] = value
    save_config(config)


def get_ensured_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SCRAPERS_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR, SCRAPERS_DIR
