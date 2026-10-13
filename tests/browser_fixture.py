"""Explicit fake market server for isolated browser tests. Never used by the product."""

import os
from pathlib import Path

from app.config import Settings
from app.main import create_app
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders

app = create_app(
    Settings(data_dir=Path(os.environ["BROWSER_TEST_DATA"])),
    NewsFixtureProviders(),
    run_scanner=False,
    news_factory=FixtureNews,
    assets_factory=FixtureAssets,
)
