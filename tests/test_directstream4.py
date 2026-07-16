import requests
import re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

print("=== Analyzing vsembed.ru for video sources ===")
url = "https://vsembed.ru/embed/tv/1396/1-1"
resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)

# Find all URLs
all_urls = re.findall(r'(https?://[^"\'<\s]+)', resp.text)

print(f"Total URLs found: {len(all_urls)}")
print()

# Categorize
for u in all_urls:
    u_lower = u.lower()
    if '.m3u8' in u_lower:
        print(f"[m3u8] {u}")
    elif '.mp4' in u_lower:
        print(f"[mp4]  {u}")
    elif '.ts' in u_lower:
        print(f"[ts]   {u}")
    elif any(x in u_lower for x in ['video', 'stream', 'source', 'media', 'cdn', 'api', 'manifest']):
        print(f"[vid]  {u}")

print()
print("=== Checking for iframes ===")
iframes = re.findall(r'<iframe[^>]*src="([^"]+)"', resp.text)
for f in iframes:
    print(f"  iframe: {f}")

print()
print("=== Checking for embedded JS variables with URLs ===")
# Look for common patterns like const/var url, source:, file:, etc.
patterns = [
    r'(?:src|file|url|source|link|video)[:\s"\']+(https?://[^"\'<\s]+)',
    r'["\'](https?://[^"\']+\.(?:m3u8|mp4))["\']',
]
for p in patterns:
    matches = re.findall(p, resp.text, re.IGNORECASE)
    for m in matches:
        print(f"  {m}")

print()
print("=== Trying to find video player config / setup ===")
# Look for common player identifiers
for keyword in ['player', 'jwplayer', 'videojs', 'plyr', 'hls', 'dash', 'shaka', 'clappr', 'flowplayer']:
    if keyword in resp.text.lower():
        idx = resp.text.lower().find(keyword)
        print(f"  Found '{keyword}' at position {idx}: ...{resp.text[max(0,idx-50):idx+200]}...")
        print()

print()
print("=== Page title: ===")
titles = re.findall(r'<title[^>]*>(.*?)</title>', resp.text, re.IGNORECASE)
print(f"  {titles}")

print()
print("=== Script tags count ===")
scripts = re.findall(r'<script[^>]*>(.*?)</script>', resp.text, re.IGNORECASE | re.DOTALL)
print(f"  Inline scripts: {len(scripts)}")
ext_scripts = re.findall(r'<script[^>]*src="([^"]+)"', resp.text, re.IGNORECASE)
print(f"  External scripts: {len(ext_scripts)}")
for s in ext_scripts:
    print(f"    {s}")
