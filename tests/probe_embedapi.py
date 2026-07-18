"""Smoketest for EmbedClient (2embed API metadata fallback).

Usage:
    python tests/probe_embedapi.py
"""

from cinnamon.embedapi import EmbedClient

c = EmbedClient()

# --- TV search ---
r = c.search_tv("breaking bad")
items = r.get("results", [])
assert items, "TV search should return results"
s = items[0]
assert s.get("id") == 1396, f"Expected tmdb_id 1396, got {s.get('id')}"
assert s.get("_media_type") == "tv"
print(f"TV search OK — {s.get('name')} (id={s.get('id')})")

# --- Movie search ---
r = c.search_movie("inception")
items = r.get("results", [])
assert items, "Movie search should return results"
s = items[0]
assert s.get("id") == 27205, f"Expected tmdb_id 27205, got {s.get('id')}"
assert s.get("_media_type") == "movie"
assert s.get("title")
print(f"Movie search OK — {s.get('title')} (id={s.get('id')})")

# --- Anime detection ---
r = c.search_tv("frieren")
items = r.get("results", [])
assert items
s = items[0]
assert "JP" in (s.get("origin_country") or [])
assert s.get("original_language") == "ja"
from cinnamon.cli import _is_anime
assert _is_anime(s)
print(f"Anime detection OK — {s.get('name')} is_anime=True")

# --- TV details ---
d = c.get_tv_details(1396)
assert d.get("number_of_seasons", 0) > 0
assert d.get("origin_country") == ["US"]
assert d.get("original_language") == "en"
print(f"TV details OK — {d.get('name')} ({d.get('number_of_seasons')} seasons)")

# --- Season details ---
s = c.get_season_details(1396, 1)
eps = s.get("episodes", [])
assert len(eps) > 0
assert eps[0].get("episode_number") == 1
assert eps[0].get("name")
print(f"Season details OK — {len(eps)} episodes, first: E{eps[0]['episode_number']} {eps[0]['name']}")

# --- Movie details ---
d = c.get_movie_details(27205)
assert d.get("title")
assert d.get("original_language") == "en"
print(f"Movie details OK — {d.get('title')}")

print()
print("All EmbedClient tests passed.")
