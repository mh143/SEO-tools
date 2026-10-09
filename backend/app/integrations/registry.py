from __future__ import annotations

from app.integrations.base import Connector
from app.integrations.wordpress import WordPressConnector

_FACTORIES = {"wordpress": WordPressConnector}

# Shown in the UI so users know what exists; none of these is implemented yet.
PLANNED = [
    {"provider": "webflow", "name": "Webflow", "status": "not_implemented"},
    {"provider": "shopify", "name": "Shopify", "status": "not_implemented"},
    {"provider": "wix", "name": "Wix", "status": "not_implemented"},
]

_override: dict[str, Connector] = {}


def get_connector(provider: str) -> Connector:
    if provider in _override:
        return _override[provider]
    if provider not in _FACTORIES:
        raise KeyError(provider)
    return _FACTORIES[provider]()


def available() -> list[dict]:
    return [{"provider": "wordpress", "name": "WordPress", "status": "available",
             "description": "Self-hosted WordPress 5.6+ over HTTPS, authorized with core Application Passwords. "
                            "No plugin required."}] + PLANNED
