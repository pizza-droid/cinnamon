import requests
import re

TMDB_ID = 1396
SEASON = 1
EPISODE = 1
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

print("=== Round 2: membed.net with SSL verify disabled ===")
url = f"https://membed.net/directstream.php?video_id={TMDB_ID}&tmdb=1&s={SEASON}&e={EPISODE}"
headers = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Referer": "https://membed.net/",
    "Origin": "https://membed.net",
}
try:
    resp = requests.get(url, headers=headers, timeout=20, verify=False)
    print(f"Status: {resp.status_code}")
    print(f"Final URL: {resp.url}")
    print(f"Length: {len(resp.text)}")
    print(f"Content: {resp.text[:1000]}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Round 3: vidsrc.to response body ===")
url = f"https://vidsrc.to/embed/tv/{TMDB_ID}/{SEASON}/{EPISODE}"
try:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    print(f"Status: {resp.status_code}")
    # Check for iframe sources and script sources
    iframes = re.findall(r'<iframe[^>]*src="([^"]+)"', resp.text)
    print(f"iframes: {iframes}")
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', resp.text)
    print(f"scripts found: {len(scripts)}")
    # Look for any URL patterns
    urls_found = re.findall(r'(https?://[^"\'<\s]+)', resp.text)
    for u in urls_found:
        if any(x in u for x in ['.m3u8', '.mp4', 'stream', 'video', 'manifest']):
            print(f"  Interesting URL: {u}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Round 4: Try other known direct sources ===")
# Try a few more services
tests = [
    ("embed.su", f"https://embed.su/embed/tv/{TMDB_ID}/{SEASON}/{EPISODE}"),
    ("superflix", f"https://superflix.net/embed/tv/{TMDB_ID}/{SEASON}/{EPISODE}"),
    ("moviesapi", f"https://moviesapi.club/tv/{TMDB_ID}-{SEASON}-{EPISODE}"),
]
for label, url in tests:
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        m3u8_in = "m3u8" in resp.text.lower()
        print(f"  [{label}] Status={resp.status_code}, Len={len(resp.text)}, m3u8={m3u8_in}")
        # check for URLs
        found = re.findall(r'(https?://[^"\'<\s]+\.(?:m3u8|mp4)[^"\'<\s]*)', resp.text)
        if found:
            print(f"    Direct URLs: {found}")
    except Exception as e:
        print(f"  [{label}] Error: {e}")

print("\n=== Round 5: Try direct API endpoints ===")
# Some sources provide JSON endpoints
api_tests = [
    ("vidsrc.to api", f"https://vidsrc.to/api/tv/{TMDB_ID}/season/{SEASON}/episode/{EPISODE}"),
    ("multiembed direct", f"https://multiembed.mov/tv/{TMDB_ID}/{SEASON}/{EPISODE}"),
]
for label, url in api_tests:
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        print(f"  [{label}] Status={resp.status_code}, Len={len(resp.text)}")
        print(f"    Content: {resp.text[:500]}")
    except Exception as e:
        print(f"  [{label}] Error: {e}")

print("\nDone.")
