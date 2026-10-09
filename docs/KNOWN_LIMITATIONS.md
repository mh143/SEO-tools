# Known limitations

Honest list of what is incomplete, untested against real services, or deliberately out of scope.

## Tested only against test doubles / mocks
* **WordPress publishing** — contract-tested against a fake WordPress that follows the documented core REST
  responses; not run against a real WordPress install (no internet in the build environment). Test with a
  staging site first. Some hosts/security plugins disable Application Passwords or the REST API.
* **Anthropic** — client code unit-tested with a stubbed SDK; no live calls were made. Prompt quality has not
  been evaluated on real pages; the mock provider used in tests produces placeholder text (clearly labelled).
* **DataForSEO** — mocked responses shaped like the v3 docs; verify field mappings with your account.
* **Stripe** — webhook handling tested with locally signed events; Checkout/Portal calls tested with stubs.
* **Crawling the public internet** — the crawler was tested against local fixture sites (via a dev-only
  SSRF allowlist) because outbound internet was blocked. Real-world HTML edge cases will surface.
* **Docker Compose / Dockerfiles / CI workflow** — written but not executed here.

## Not implemented
* Additional connectors (Webflow, Shopify, Wix) — interface exists; shown as "not yet implemented".
* Google Search Console (connected search data) and brand-mention / AI-citation monitoring data sources.
* Email verification, password reset, MFA/SSO. (Invitations work via shareable links; SMTP is only used for alerts.)
* PDF generation (HTML report is print-friendly; use the browser's "Save as PDF").
* Per-page AI content analysis outside of findings (content plans are generated from content findings).
* Content-Security-Policy for the web app; independent security review / penetration test.
* Webhook event ordering: subscription updates are applied in arrival order (no `event.created` comparison).
* Rate limiting is fixed-window per IP; no global anti-abuse for signups beyond that.

## Product/methodology limitations
* GEO/AEO checks are heuristics (e.g. claim detection is a pattern match with false positives). The GEO score is an
  internal heuristic, not an industry standard, and predicts nothing about rankings or AI citations.
* Duplicate-title/description checks only cover crawled pages; orphan-page detection is relative to the crawl.
* Image alt suggestions are based on filename and surrounding text only (no image understanding) and are marked low confidence.
* JavaScript rendering only fetches same-site sub-resources and does not execute WebSockets or service workers,
  so some SPAs may render incompletely. Rendering requires Chromium on workers.
* WordPress title edits change the post title, which most themes use for both `<title>` and the H1.
* Verification of a change behind an aggressive CDN may fail until the cache is purged (the fix then shows
  `failed` with that explanation and can be re-verified).
* Celery "inline" mode (`TASK_BACKEND=inline`) loses jobs on restart — development only.
