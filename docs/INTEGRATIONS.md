# Integrations

## Connector interface (`backend/app/integrations/base.py`)

| Method | Purpose |
|---|---|
| authorization (provider specific) | Official authorization flow; credentials stored encrypted server-side |
| `verify_identity(creds)` | Confirms the account and the site it controls (must match the website's host) |
| `discover_capabilities(creds)` | Per-operation `{supported, reason, rollback, notes}` for *this* site and user |
| `locate(creds, url, extracted)` | Map a crawled URL to a provider resource (or `None`) |
| `read(creds, ref)` | Current editable state |
| `apply(creds, ref, operation, params)` | Allowlisted operation only; returns original state, new state, provider response, rollback ref |
| `rollback(creds, rollback_ref)` | Restores the original value — refuses if the content changed since (conflict) |
| `disconnect` | Credentials are deleted locally (users should also revoke them at the provider) |

Operations: `set_title`, `set_meta_description`, `set_image_alt`, `content_insert_after_heading`,
`content_append`, `content_replace_href`, `content_link_phrase`, `add_json_ld`, `set_canonical`,
`create_redirect`, `set_robots`. Operations a connector does not declare as supported are never attempted;
the fix is offered as copy/export instead with the connector's reason.

All connector HTTP traffic goes through the SSRF-safe fetcher, and redirects are never followed with
credentials attached.

## WordPress (implemented)

* **Requirements:** self-hosted WordPress 5.6+ (core Application Passwords), served over HTTPS for the
  authorization flow, REST API reachable, a user with the Editor or Administrator role.
* **No plugin required.**
* **Authorization flow:** `GET /wp-json/` → `authentication["application-passwords"].endpoints.authorization`
  → user approves on their site at `/wp-admin/authorize-application.php?app_name=…&app_id=…&success_url=…&reject_url=…`
  → WordPress redirects to `/api/integrations/wordpress/callback?state=…&site_url=…&user_login=…&password=…`.
  The `state` is single-use, expires after 20 minutes and is bound to the org; only org admins can complete it.
  WordPress only accepts HTTPS `success_url`s, so `PUBLIC_APP_URL` must be HTTPS in production.
* **Manual alternative:** paste a username and an application password created under *Users → Profile*.
* **Identity check:** `GET /wp/v2/users/me?context=edit`; the site's `home` must be the same host as the website.
* **Capabilities:** derived from the user's capabilities (`edit_published_posts/pages`, `edit_others_posts/pages`).

| Operation | Support | How |
|---|---|---|
| `set_title` | ✅ (rollback) | `POST /wp/v2/{posts|pages}/{id} {title}`. Note: in most themes the post title drives both `<title>` and the H1. |
| `set_image_alt` | ✅ (rollback) | Edits the `<img alt>` in `content.raw` (matching `src`), and media `alt_text` when the attachment id is known |
| `content_insert_after_heading` | ✅ (rollback) | Inserts sanitized HTML after the uniquely matching heading (block content wrapped in a Custom HTML block) |
| `content_append` | ✅ (rollback) | Appends a sanitized FAQ section |
| `content_replace_href` | ✅ (rollback) | Replaces matching `href`s inside post content (menus/widgets untouched) |
| `content_link_phrase` | ✅ (rollback) | Links the first plain-text occurrence of a phrase |
| `set_meta_description` | ❌ | Core has no field; SEO plugin fields aren't writable through core REST |
| `add_json_ld` | ❌ | No core API for `<head>`; `<script>` in content is filtered for most users |
| `set_canonical`, `create_redirect`, `set_robots` | ❌ | No core API |

**URL → resource mapping:** WordPress 5.5+ prints `<link rel="alternate" type="application/json" href="/wp-json/wp/v2/pages/ID">`;
the connector uses it (and verifies the resource's `link` equals the page URL), falling back to a slug lookup.
Homepages rendered by theme templates, archives and custom post types may not map; publishing is then refused
up-front (preflight) with an explanation.

**Verification:** after the API accepts a change, the live page is fetched (with no-cache headers, then a
cache-busting query) and the expected change is checked (e.g. `<title>` contains the new title, `<img>` with
that `src` has the new alt). Retries every 5 minutes up to 5 checks; then `failed` with an explanation (often a CDN cache).

**Testing status:** covered by contract tests against `tests/fixtures/fake_wordpress.py`, which implements the
documented responses of the endpoints above and renders pages from stored state. It has **not** been run
against a real WordPress installation in this environment (no internet access). Test with a staging site first.

## Anthropic (AI)
`AI_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-opus-5-5`), `AI_EFFORT`
(default `medium`). Uses the Messages API with structured outputs (`output_config.format` JSON schema) and,
by default, the server-side refusal fallback beta (`server-side-fallback-2026-07-01`, `fallbacks="default"`);
disable with `AI_REFUSAL_FALLBACK=false`. Output is re-validated locally regardless. Not exercised against
the live API during development (no key); the client code is unit-tested with a stubbed SDK client.

## DataForSEO (keyword data)
`DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`. Endpoints: `keywords_data/google_ads/search_volume/live`,
`dataforseo_labs/google/bulk_keyword_difficulty/live`, `dataforseo_labs/google/keyword_ideas/live`.
Contract-tested with mocked responses; verify field mappings against your account before relying on them.

## Stripe (billing)
Create three recurring monthly prices in CAD and set `STRIPE_PRICE_STARTER/PRO/AGENCY`. Configure a webhook
endpoint at `{PUBLIC_APP_URL}/api/billing/webhook` with events: `checkout.session.completed`,
`customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`,
`invoice.paid`, `invoice.payment_succeeded`, `invoice.payment_failed`. Enable the Customer Portal in the
Stripe dashboard. Test locally with `stripe listen --forward-to localhost:8000/api/billing/webhook`.

## Not implemented
Webflow, Shopify, Wix connectors; Google Search Console; brand-mention / AI-citation monitoring data sources.
They are shown in the UI as "not yet implemented".
