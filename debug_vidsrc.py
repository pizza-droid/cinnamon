import asyncio
from playwright.async_api import async_playwright

async def debug_vidsrc():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()
        
        urls = []
        page.on('response', lambda r: urls.append({'url': r.url, 'type': r.request.resource_type}))
        page.on('console', lambda msg: print(f'CONSOLE: {msg.text}'))
        
        await page.goto('https://vidsrc.pm/embed/tv/2224/1/1', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(10)
        
        frames = page.frames
        print(f'Frames: {len(frames)}')
        for i, f in enumerate(frames):
            print(f'  Frame {i}: {f.url}')
        
        has_video = await page.eval_on_selector_all('video', 'els => els.length')
        print(f'Video elements: {has_video}')
        
        has_iframe = await page.eval_on_selector_all('iframe', 'els => els.length')
        print(f'Iframe elements: {has_iframe}')
        
        m3u8_urls = [u for u in urls if '.m3u8' in u['url'].lower()]
        print(f'm3u8 URLs found: {len(m3u8_urls)}')
        for u in m3u8_urls:
            print(f'  {u["url"]}')
        
        video_urls = [u for u in urls if any(x in u['url'].lower() for x in ['video', 'stream', 'cdn', 'play', 'hls', 'media'])]
        print(f'Potential video URLs: {len(video_urls)}')
        for u in video_urls[:10]:
            print(f'  [{u["type"]}] {u["url"][:100]}')
        
        await page.screenshot(path=r'C:\Users\Administraitor\cinnamon\vidsrc_debug.png')
        print('Screenshot saved')
        
        await browser.close()

asyncio.run(debug_vidsrc())
