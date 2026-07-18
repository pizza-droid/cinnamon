from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScraperResult:
    title: str
    m3u8_url: str
    referer: Optional[str] = None
    user_agent: Optional[str] = None
    headers: dict = field(default_factory=dict)
    subtitle_url: Optional[str] = None

    def __post_init__(self):
        if not self.title:
            raise ValueError("ScraperResult.title is required")
        if not self.m3u8_url:
            raise ValueError("ScraperResult.m3u8_url is required")
        if not (self.m3u8_url.startswith("http") or self.m3u8_url.startswith("magnet:")):
            raise ValueError(f"ScraperResult.m3u8_url must be a valid URL, got: {self.m3u8_url}")


class BaseScraper(ABC):
    name: str = ""
    description: str = ""
    config_schema: dict = {}

    @abstractmethod
    def search(self, query: str) -> list[dict]:
        ...

    @abstractmethod
    def resolve(self, episode_info: dict) -> Optional[ScraperResult]:
        ...
