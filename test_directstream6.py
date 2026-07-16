import requests
import re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

print("=== vidlink.pro response analysis ===")
url = "https://vidlink.pro/tv/1396/1/1"
resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)
print(f"Status: {resp.status_code}, Length: {len(resp.text)}")

# Check for iframes
iframes = re.findall(r'<iframe[^>]*src="([^"]+)"', resp.text)
print(f"Iframes: {iframes}")

# Check for video sources
sources = re.findall(r'<source[^>]*src="([^"]+)"', resp.text)
print(f"Video sources: {sources}")

# Check for any video-related URLs
all_urls = re.findall(r'(https?://[^"\'<\s]+)', resp.text)
for u in all_urls:
    if any(x in u.lower() for x in ['.m3u8', '.mp4', 'stream', 'video', 'source', 'cdn', 'media']):
        print(f"  Relevant URL: {u}")

# Find all script tags
scripts = re.findall(r'<script[^>]*src="([^"]+)"', resp.text)
print(f"\nExternal scripts ({len(scripts)}):")
for s in scripts[:20]:
    print(f"  {s}")

# Find embed URLs pointing to iframe services
embed_patterns = re.findall(r'(?:embed|src|href)["\']?\s*[:=]\s*["\']([^"\']*(?:cloudnestra|cloudorchestranova|rcp|embed)[^"\']*)["\']', resp.text, re.IGNORECASE)
print(f"\nEmbed references:")
for p in embed_patterns:
    print(f"  {p}")

# Check for internal state or config
for keyword in ['const ', 'var ', 'let ', 'data-', 'window.', 'player']:
    parts = [line for line in resp.text.split('\n') if keyword.lower() in line.lower()]
    for p in parts[:5]:
        p = p.strip()
        if len(p) > 30 and any(x in p.lower() for x in ['url', 'src', 'http', 'm3u8', 'file', 'source', 'video', 'stream']):
            print(f"\n  [{keyword}]: {p[:300]}")

print(f"\n=== Checking sub-URLs with Playwright-style headers ===")
# Try to fetch with additional headers that might bypass protection
extra_headers = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://vidlink.pro/",
    "Origin": "https://vidlink.pro",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "iframe",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}
url2 = "https://vidlink.pro/tv/1396/1/1"
resp2 = requests.get(url2, headers=extra_headers, timeout=15)
print(f"With full headers: Status={resp2.status_code}, Len={len(resp2.text)}")
if "m3u8" in resp2.text.lower():
    m3u8s = re.findall(r'(https?://[^"\'<\s]+\.m3u8[^"\'<\s]*)', resp2.text)
    print(f"m3u8 URLs: {m3u8s}")

print(f"\n=== Checking if cloudnestra.com iframe works ===")
# The sources.js shows that vsembed uses cloudnestra.com/rcp/{hash} for actual video
# Let's try fetching one
test_url = "https://cloudnestra.com/rcp/MzI3YTM5YWE1N2MxY2IyMTBmMDkwNDk0Y2RlZWJkMmQ6TVRFNVpYQk5SbmxsUkc5eFozVlRWMEp0Y1dOc1dqQmhlR1JpYzJ4U00wNXhaRFYwUWtNMlNqTXlTVmRZYlM5d01FSXZVVzlKYjNSTFZGcEtkR0ZoWkRGS1IyNVpXVE53Wmxjek5VOUVla1JtTUhWNVN6RnNieTlPWmpoTldrVk5UMjVsYkhneFVISjFZVkoyZFZac1REQm1MemQyWVZsT05tNTJVVXBZTWt0bkwxbFlkWFpNVUhRNFQyMUxTM1ZwT0ZsVk4yTkxkMVV6Y25CNk1UTXhjSEIyUmtWVGVWVTRjRTV6WnpaV1UxZDZXVGhJTVRKVk1sWldlWFZxUkhONU5IVnVSWEZ4Ym5wS2ExQkhiR3hzYmtVNVFtdHVVVTUxV1RJeksybFFjelpIY2xSdlFVa3dhVVJ4T1dNNFNUSjJSMHRHZHpaa1dYSlNUbXN3Y2l0Sk5IWlJaSGh4VldZeVlrdzVhbmh3VW05TFYzZERjM1JEUmtsbk5GUnNaRmxyUm5nMGVrMTFPRlZVYUc5WUt6ZGxZbFJ0ZEVKUk1HZEhhRlo2Ynk5b1YzUmFjM1pNVVhSbFVHeFlUSE5OTDFreVZYSXhjMHRFTUhOTmVGSXhRMGg0WmxoWVowOU5hbVpMWTFoUU0ySm1XVFl5VW5kSllsZHdPRkJFU0hRM1dEaG5TVmQxYTI1U2VrOTBPWE5wUVV3MEsySk5XVWhhYjBONFl6bHRhVEU0VXl0Tk9WWndWR2RGVTNneVZscE9PRWczVkc4elRqWTFMMWgwS3pGMEsxZ3ZhVU5JVkhjeWFrTk9kaloyVXpsd2MwUm1PRFpSVlhaa04wcGxWbmxXYkhFeGJGaFNNbnBMTldsR1kzTllXblJZU1M5UFVGcEtLelYxVGxFdlFWUTRkRlZsTDNBd04zTkdPRGx4UVZsRU5XUmxPSEpsTTAxcE1HUkhOM1owUW5wdE1rVm9ZMFoxVkdaRVNsSTFLeTlsWVhjeE5XMXRaRk5oUVVSR1pWTjNlV05MT1RBM1RsUktZakIzWlV0MllXVm5iR3gzY21WRU1tTTJSeXM0Uld4cWJDOWpaM1JaUTNwdVJVTTJhM0p6VjJaTk9ISmFTRnBhTTFSemF6VjVhVEJxTVZaNVR6TldlSEZZZUhGQ1lWb3JjMlZGZEdGb1RESTBNRFZaU2t0MWVqQkVSV1JJVXpaT2JXUm9ibmx2YmtJSVZERXJOazVZWTFBMVRIb3dkVTlyV2xoQlVsWmxjQzlJWm5wcWRUSTJVMFl2U0hOTWNEZHNLelJ3V1doclNVdHlialYxVG1SMU1tdGhNMHM1UW5aWGJXNXVjMmxyV1ZOMWJYa3lMMUJ2VkVabGJHTmllRVpzUlhWS1ZWbGFOemRMU25BNFJXODBNbUZxUjFCSVNsQTNSQ3RzTjNaMGVHNTJWM0ZwYzNneFQyWnlPV3hDV2paMVZUTTFVVmg0UmxNd1JIWnRabW9yWlRnd04yNTBLMDkxYTNCWlltOUNjVE0zU21KQ2REQkhWVVY2Ym5Fd1ZFRmpNMkU1TlZKWFRuTmFhbk5UYVZwSE9GbzBRVkpWWVdwUmEydHlOekp3YUdWRk9FSnJSbVYzV0dkckwxZzVXa2RMZHk5TVdYbG9NSEl4UzFRMGJrUndja2hyUVRaVE9IWXljbWN3TDFaTVRHaGhNREp2WTNWdVJsRnZUbmRJWVVwNWVtVk1TRkF3VGl0Q09YTTBSa0ZqU0U5S1VsUnJOa3BYTkZWbmNrbDVLME5UV0ZseWNVRXlkRkpTV2pseFNYYzNOR3ByTkZOcE5FUkdOelJFT1VaRU1GaEhPVnBMV2t4QmVreFZTREYwZVZGVFFsWk9RVEJpU2tGNFluaEJiVmxPYkVGVFYyTkRjR3AxUjBweGJGa3lUWEJRWmpkQk5TODVaR05aTm1jMVlsQlJOa3BwTTBzeU9XNDJjM2g0SzFWS09WSnpTMHRDUkRWWllraE5URmN2ZEZkR1kxUTVkRU5QZDFoUlIyaGFWalZNVTNObFRVaFVTWEJJ"
try:
    r = requests.get(test_url, headers={"User-Agent": UA, "Referer": "https://vsembed.ru/"}, timeout=15)
    print(f"Status: {r.status_code}, Length: {len(r.text)}")
    print(f"Preview: {r.text[:1000]}")
except Exception as e:
    print(f"Error: {e}")

print("\nDone.")
