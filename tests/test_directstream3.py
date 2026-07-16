import requests
import re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

# Follow the membed redirect
print("=== Full membed.net response analysis ===")
url = "https://membed.net/directstream.php?video_id=1396&tmdb=1&s=1&e=1"
headers = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Referer": "https://membed.net/",
    "Origin": "https://membed.net",
}
resp = requests.get(url, headers=headers, timeout=20, verify=False)
print(f"Full response:")
print(resp.text)
print(f"\n--- Response headers ---")
for k, v in resp.headers.items():
    print(f"  {k}: {v}")

print("\n\n=== vsembed.ru (from vidsrc.to iframe) ===")
url2 = "https://vsembed.ru/embed/tv/1396/1-1"
try:
    resp2 = requests.get(url2, headers={"User-Agent": UA}, timeout=15)
    print(f"Status: {resp2.status_code}")
    m3u8_urls = re.findall(r'(https?://[^"\'<\s]+\.m3u8[^"\'<\s]*)', resp2.text)
    if m3u8_urls:
        print(f"m3u8 URLs: {m3u8_urls}")
    else:
        # Look for any interesting URLs
        all_urls = re.findall(r'(https?://[^"\'<\s]+)', resp2.text)
        for u in all_urls:
            if any(x in u.lower() for x in ['m3u8', '.mp4', 'stream', 'video', 'api', 'source', 'manifest', '.ts']):
                print(f"  Interesting: {u}")
        print(f"Page length: {len(resp2.text)}")
        print(f"Content preview: {resp2.text[:1500]}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== superflix.net content ===")
url3 = f"https://superflix.net/embed/tv/1396/1/1"
try:
    resp3 = requests.get(url3, headers={"User-Agent": UA}, timeout=15)
    print(f"Status: {resp3.status_code}")
    m3u8_urls = re.findall(r'(https?://[^"\'<\s]+\.m3u8[^"\'<\s]*)', resp3.text)
    if m3u8_urls:
        print(f"m3u8 URLs: {m3u8_urls}")
    else:
        iframes = re.findall(r'<iframe[^>]*src="([^"]+)"', resp3.text)
        print(f"iframes: {iframes}")
        print(f"Preview: {resp3.text[:1500]}")
except Exception as e:
    print(f"Error: {e}")

print("\nDone.")
