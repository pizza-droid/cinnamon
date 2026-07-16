import asyncio
import time as _time
from typing import Optional

from ..errors import (
    ScraperNetworkError,
    ScraperNoStreamError,
    ScraperParseError,
)
from .base import BaseScraper, ScraperResult

_DOMAINS = [
    ("vidsrc.pm", "https://vidsrc.pm/embed/tv/{tmdb_id}/{season}/{episode}"),
    ("vidsrc.to", "https://vidsrc.to/embed/tv/{tmdb_id}/{season}/{episode}"),
    ("vidsrc.in", "https://vidsrc.in/embed/tv/{tmdb_id}/{season}/{episode}"),
    ("vidsrc.net", "https://vidsrc.net/embed/tv/{tmdb_id}/{season}/{episode}"),
    ("vidsrc.xyz", "https://vidsrc.xyz/embed/tv/{tmdb_id}/{season}/{episode}"),
    ("vidsrc.cc", "https://vidsrc.cc/embed/tv/{tmdb_id}/{season}/{episode}"),
]

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"


class VidSrcScraper(BaseScraper):
    name = "vidsrc"
    description = "Scrapes m3u8 streams from vidsrc domains using Playwright"

    def search(self, query):
        return []

    def resolve(self, episode_info):
        tmdb_id = episode_info.get("tv_id") or episode_info.get("tmdb_id")
        show = episode_info.get("show", "?")
        season = episode_info.get("season", 1)
        episode = episode_info.get("episode", 1)

        if not tmdb_id:
            raise ScraperParseError(self.name, "Missing tv_id/tmdb_id in episode_info")

        last_error = None
        for domain, url_template in _DOMAINS:
            embed_url = url_template.format(tmdb_id=tmdb_id, season=season, episode=episode)
            try:
                m3u8_url = _playwright_resolve(embed_url, timeout=30)
                if m3u8_url:
                    return ScraperResult(
                        title=f"{show} S{season:02d}E{episode:02d}",
                        m3u8_url=m3u8_url,
                        referer=embed_url,
                        user_agent=_UA,
                    )
            except ScraperNoStreamError:
                continue
            except Exception as e:
                last_error = e
                continue

        if last_error:
            raise last_error if isinstance(last_error, ScraperNoStreamError) else ScraperNoStreamError(self.name)
        raise ScraperNoStreamError(self.name)


def _playwright_resolve(embed_url: str, timeout: int = 30) -> Optional[str]:
    return asyncio.run(_async_resolve(embed_url, timeout))


async def _async_resolve(embed_url: str, timeout: int = 30) -> Optional[str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ScraperNetworkError(
            "vidsrc",
            "Playwright is required for the vidsrc scraper. Install it with: pip install playwright && python -m playwright install chromium"
        )

    found_urls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=_UA,
        )
        page = await context.new_page()

        await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        """)

        all_urls = []
        page.on('response', lambda r: all_urls.append(r.url))

        try:
            await page.goto(embed_url, wait_until="domcontentloaded", timeout=timeout * 1000)
        except Exception as e:
            await browser.close()
            raise ScraperNetworkError("vidsrc", f"Navigation failed: {e}")

        deadline = _time.time() + timeout
        while _time.time() < deadline:
            await asyncio.sleep(1)
            for u in all_urls:
                if '.m3u8' in u.lower() and u not in found_urls:
                    found_urls.append(u)
            if found_urls:
                break

        await browser.close()

    if not found_urls:
        raise ScraperNoStreamError("vidsrc")

    master = [u for u in found_urls if 'master.m3u8' in u]
    return master[0] if master else found_urls[0]
