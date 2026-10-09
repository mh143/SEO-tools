import glob
import os

import pytest

from app.core.config import get_settings
from tests.fixtures.site import FixtureSite

CHROME = os.environ.get("CHROMIUM_EXECUTABLE_PATH") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))), "")

SPA = "<html><head><title>SPA</title></head><body><div id='root'></div><script src='/app.js'></script></body></html>"
JS = ("document.getElementById('root').innerHTML='<h1>Rendered heading</h1><p>hello from js</p>';"
      "fetch('http://169.254.169.254/latest/meta-data/').catch(()=>{});"
      "fetch('http://127.0.0.1:1/x').catch(()=>{});")


@pytest.mark.skipif(not CHROME, reason="Chromium not available")
async def test_render_routes_all_requests_through_safe_fetcher(monkeypatch):
    from app.crawler.renderer import Renderer

    s = get_settings()
    monkeypatch.setattr(s, "ssrf_dev_allow_hosts", "127.0.0.1")
    monkeypatch.setattr(s, "chromium_executable_path", CHROME)
    with FixtureSite({"/": (200, {}, SPA), "/app.js": (200, {"Content-Type": "application/javascript"}, JS)}) as site:
        async with Renderer() as r:
            html = await r.render(site.base + "/")
    assert "Rendered heading" in html
    assert sorted(site.hits) == ["/", "/app.js"]
