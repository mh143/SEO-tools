from __future__ import annotations

from app.integrations.base import Connector
from app.integrations.shopify import ShopifyConnector
from app.integrations.wix import WixConnector
from app.integrations.wordpress import WordPressConnector

_FACTORIES = {"wordpress": WordPressConnector, "shopify": ShopifyConnector, "wix": WixConnector}

# Providers that publish changes (as opposed to data sources such as Google Search Console).
PUBLISHING_PROVIDERS = tuple(_FACTORIES)
DATA_PROVIDERS = ("google_search_console",)

PLANNED = [
    {"provider": "webflow", "name": "Webflow", "kind": "publishing", "status": "not_implemented",
     "description": "Planned: CMS collection items and page SEO settings via the Webflow Data API."},
]

_override: dict[str, Connector] = {}


def get_connector(provider: str) -> Connector:
    if provider in _override:
        return _override[provider]
    if provider not in _FACTORIES:
        raise KeyError(provider)
    return _FACTORIES[provider]()


def available() -> list[dict]:
    from app.integrations import search_console

    return [
        {"provider": "wordpress", "name": "WordPress", "kind": "publishing", "status": "available",
         "description": "Self-hosted WordPress 5.6+ over HTTPS, authorized with core Application Passwords. "
                        "No plugin required.",
         "supports": ["Titles & H1", "Image alt text", "Answers & FAQs", "Internal links"]},
        {"provider": "shopify", "name": "Shopify", "kind": "publishing", "status": "available",
         "description": "Products, collections, pages and blog posts via a custom app Admin API token.",
         "supports": ["SEO titles", "Meta descriptions", "Body content & alt text", "URL redirects"]},
        {"provider": "wix", "name": "Wix", "kind": "publishing", "status": "available",
         "description": "Blog posts and store products via a Wix API key and site ID.",
         "supports": ["SEO titles", "Meta descriptions", "Post titles & product names"]},
        {"provider": "google_search_console", "name": "Google Search Console", "kind": "data",
         "status": "available" if search_console.configured() else "needs_configuration",
         "description": "Read-only clicks, impressions, CTR and average position from Google (OAuth).",
         "supports": ["Clicks & impressions", "Top queries", "Top pages", "Average position"],
         "configuration_note": None if search_console.configured() else
         "The server administrator must set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."},
    ] + PLANNED
