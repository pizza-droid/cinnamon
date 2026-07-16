import requests
import re
import base64

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

# Get vsembed page to extract the iframe URL
print("=== Step 1: Get vsembed.ru iframe URL ===")
url = "https://vsembed.ru/embed/tv/1396/1-1"
resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)

# Find the iframe with cloudorchestranova.com
matches = re.findall(r'<iframe[^>]*src="([^"]*cloudorchestranova\.com[^"]*)"', resp.text)
if not matches:
    matches = re.findall(r'<iframe[^>]*src="([^"]*)"', resp.text)

iframe_url = None
for m in matches:
    if m.startswith("//"):
        iframe_url = "https:" + m
    else:
        iframe_url = m
    break

print(f"iframe URL: {iframe_url}")

if iframe_url:
    print(f"\n=== Step 2: Fetch iframe ===")
    try:
        iframe_resp = requests.get(iframe_url, headers={"User-Agent": UA, "Referer": url}, timeout=15)
        print(f"Status: {iframe_resp.status_code}")
        print(f"Length: {len(iframe_resp.text)}")
        print(f"Preview: {iframe_resp.text[:2000]}")
        
        # Check for m3u8
        m3u8 = re.findall(r'(https?://[^"\'<\s]+\.m3u8[^"\'<\s]*)', iframe_resp.text)
        if m3u8:
            print(f"\nm3u8 URLs: {m3u8}")
        
        # Check for any URLs
        urls = re.findall(r'(https?://[^"\'<\s]+)', iframe_resp.text)
        print(f"\nAll URLs in iframe:")
        for u in urls:
            print(f"  {u}")
            
    except Exception as e:
        print(f"Error fetching iframe: {e}")

print(f"\n=== Step 3: Try to decode the base64-looking parameter ===")
# The iframe URL has a long base64 parameter - let's try to decode
rcp_pattern = r'/rcp/([A-Za-z0-9+/=]+)'
rcp_match = re.search(rcp_pattern, iframe_url) if iframe_url else None
if rcp_match:
    encoded = rcp_match.group(1)
    try:
        # Add padding
        padding = 4 - len(encoded) % 4
        if padding != 4:
            encoded += '=' * padding
        decoded = base64.b64decode(encoded)
        print(f"Decoded RCP data:")
        print(decoded[:1000])
    except Exception as e:
        print(f"Could not decode: {e}")

print(f"\n=== Step 4: Fetch sources.js ===")
try:
    sources = requests.get("https://vsembed.ru/sources.js?t=1745104089", headers={"User-Agent": UA, "Referer": url}, timeout=15)
    print(f"Status: {sources.status_code}, Length: {len(sources.text)}")
    print(f"Content:")
    print(sources.text[:3000])
    
    # Find any URLs
    urls = re.findall(r'(https?://[^"\'<\s]+)', sources.text)
    print(f"\nURLs found:")
    for u in urls:
        print(f"  {u}")
except Exception as e:
    print(f"Error: {e}")

print(f"\n=== Step 5: Try different direct URL approaches ===")
# Some services use simpler patterns
direct_tests = [
    ("multiembed direct video", f"https://multiembed.mov/video.php?video_id={1396}&tmdb=1&s=1&e=1"),
    ("multiembed alt", f"https://multiembed.mov/tv/{1396}/1/1"),
    ("flickystream", f"https://flickystream.com/embed/tv/{1396}/1/1"),
    ("dbgo", f"https://dbgo.fun/tv/{1396}/1/1"),
    ("vidlink", f"https://vidlink.pro/tv/{1396}/1/1"),
]
for label, u in direct_tests:
    try:
        r = requests.get(u, headers={"User-Agent": UA}, timeout=10, allow_redirects=True)
        has_m3u8 = "m3u8" in r.text.lower() if r.text else False
        has_mp4 = ".mp4" in r.text.lower() if r.text else False
        print(f"  [{label}] Status={r.status_code}, Len={len(r.text)}, m3u8={has_m3u8}, mp4={has_mp4}")
        if has_m3u8:
            m3u8_urls = re.findall(r'(https?://[^"\'<\s]+\.m3u8[^"\'<\s]*)', r.text)
            print(f"    Found: {m3u8_urls}")
    except Exception as e:
        print(f"  [{label}] Error: {e}")

print(f"\nDone.")
