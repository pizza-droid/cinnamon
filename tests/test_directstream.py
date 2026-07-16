import requests
import sys
import json

TMDB_ID = 1396  # Breaking Bad
SEASON = 1
EPISODE = 1

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

urls_to_try = [
    ("multiembed.mov", f"https://multiembed.mov/directstream.php?video_id={TMDB_ID}&tmdb=1&s={SEASON}&e={EPISODE}"),
    ("membed.net", f"https://membed.net/directstream.php?video_id={TMDB_ID}&tmdb=1&s={SEASON}&e={EPISODE}"),
]

headers_sets = [
    ("basic UA", {
        "User-Agent": UA,
        "Accept": "*/*",
    }),
    ("with referer (multiembed)", {
        "User-Agent": UA,
        "Accept": "*/*",
        "Referer": "https://multiembed.mov/",
        "Origin": "https://multiembed.mov",
    }),
    ("with referer (membed)", {
        "User-Agent": UA,
        "Accept": "*/*",
        "Referer": "https://membed.net/",
        "Origin": "https://membed.net",
    }),
]

SEP = "-" * 70
print(SEP)
print(f"Testing directstream URLs for TMDB ID {TMDB_ID} (Breaking Bad) S{SEASON:02d}E{EPISODE:02d}")
print(SEP)

for domain, url in urls_to_try:
    print(f"\nDOMAIN: {domain}")
    print(f"URL:    {url}")

    for label, headers in headers_sets:
        print(f"\n  [{label}]")
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            text = resp.text.strip()
            print(f"    Status:    {resp.status_code}")
            print(f"    Final URL: {resp.url}")
            print(f"    Length:    {len(text)} bytes")
            print(f"    Preview:   {text[:500]}")
            if resp.status_code != 200:
                print(f"    RESULT: Non-200 status")
            elif not text:
                print(f"    RESULT: Empty response body")
            elif "File not found" in text:
                print(f"    RESULT: Contains 'File not found'")
            elif text.startswith("http"):
                print(f"    RESULT: Direct URL found!")
            elif ".m3u8" in text:
                import re
                matches = re.findall(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', text)
                print(f"    RESULT: m3u8 URLs found: {matches}")
            else:
                print(f"    RESULT: Unexpected content")
        except requests.Timeout:
            print(f"    RESULT: Timeout")
        except requests.ConnectionError as e:
            print(f"    RESULT: Connection error: {e}")
        except Exception as e:
            print(f"    RESULT: Error: {e}")

print(f"\n{SEP}")
print("Testing alternate endpoints...")
print(SEP)

alt_urls = [
    ("vidsrc embed", f"https://vidsrc.to/embed/tv/{TMDB_ID}/{SEASON}/{EPISODE}"),
    ("vidsrc pm", f"https://vidsrc.pm/embed/tv/{TMDB_ID}/{SEASON}/{EPISODE}"),
    ("2embed", f"https://www.2embed.cc/embedtv/{TMDB_ID}&s={SEASON}&e={EPISODE}"),
    ("autoembed", f"https://autoembed.cc/embedtv/{TMDB_ID}&s={SEASON}&e={EPISODE}"),
]

for label, url in alt_urls:
    print(f"\n  [{label}]")
    print(f"    URL: {url}")
    try:
        resp = requests.get(url, headers={"User-Agent": UA, "Accept": "*/*"}, timeout=10, allow_redirects=True)
        print(f"    Status: {resp.status_code}, Final: {resp.url}, Length: {len(resp.text)}")
        has_m3u8 = "m3u8" in resp.text.lower() if resp.text else False
        print(f"    Contains m3u8: {has_m3u8}")
    except Exception as e:
        print(f"    Error: {e}")

print(f"\n{SEP}")
print("Done.")
