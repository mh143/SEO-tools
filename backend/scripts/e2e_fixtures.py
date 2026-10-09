"""Start the local fixture website (port 8301) and fake WordPress (port 8302) for end-to-end tests.

These are test doubles bound to 127.0.0.1; the backend must run with SSRF_DEV_ALLOW_HOSTS=127.0.0.1
(development/test only — refused in production).
"""

import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fixtures.demo_site import demo_site  # noqa: E402
from tests.fixtures.fake_wordpress import FakeWordPress  # noqa: E402

if __name__ == "__main__":
    site = demo_site(port=8301)
    wp = FakeWordPress(port=8302)
    with site, wp:
        print(f"demo site: {site.base}  fake wordpress: {wp.base}", flush=True)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *a: stop.set())
        try:
            stop.wait()
        except KeyboardInterrupt:
            pass
