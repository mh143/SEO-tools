# Security

## Threat model highlights
Users submit arbitrary URLs and connect third-party sites; crawled content is attacker-controlled and is fed
to an LLM; the app stores CMS credentials and handles billing. Controls below are covered by automated tests
(`backend/tests/test_ssrf.py`, `test_tenancy.py`, `test_ai_validation.py`, `test_billing.py`, `test_wordpress.py`, e2e).

## SSRF
* Only `http`/`https`; no embedded credentials; ports limited to `CRAWLER_ALLOWED_PORTS` (80, 443).
* Hostnames like `localhost`, `*.local`, `*.internal`, single-label names, and legacy IPv4 forms (`127.1`,
  `0x7f000001`, `2130706433`) are rejected.
* **Connect-time enforcement:** a custom httpcore network backend resolves the host once, rejects the
  request if *any* address is non-public (loopback, RFC1918, link-local incl. 169.254.169.254, CGNAT,
  ULA incl. fd00:ec2::254, multicast, reserved, NAT64/6to4/Teredo, IPv4-mapped), then connects to the
  validated IP. This defeats DNS rebinding (tested by switching DNS answers between calls).
* Redirects followed manually (max 5), each hop re-validated; loops detected.
* Response size caps (streamed), gzip decompression capped, connect/read/total timeouts, environment proxies ignored.
* JS rendering: the browser never opens network connections; every request is fulfilled by the safe fetcher,
  third-party and non-GET requests are aborted, service workers/downloads disabled.
* Sitemap XML parsed with entities, DTDs and network access disabled (XXE test).
* `SSRF_DEV_ALLOW_HOSTS` exists for local fixtures only and is refused in production.

## Respecting site access controls
robots.txt honoured (RFC 9309: 5xx ⇒ disallow all), no logins, no form submission, 401/403 reported not bypassed.

## Authentication & sessions
Argon2id hashes; constant-time-ish login for unknown users; per-IP and per-email login rate limits;
random 256-bit session tokens stored as SHA-256; HttpOnly + SameSite=Lax cookies (`Secure` required in production);
CSRF double-submit header on unsafe methods; password change revokes other sessions; admin deactivation revokes sessions.

## Tenant isolation & authorization
Every org-scoped route resolves membership first (non-members get 404) and loads rows with `org_id` filters
(`scoped_get`). Cross-tenant tests attempt reads and writes on every resource type via both the other org's id
and IDOR with the attacker's own org id. Role checks: viewer/editor/admin/owner; approvals, publishing,
integrations require admin; billing and org deletion require owner.

## Secrets
Integration credentials encrypted with Fernet (`ENCRYPTION_KEYS`, rotation via MultiFernet), never serialized to
the frontend, deleted on disconnect. API keys only server-side. Audit log scrubs secret-looking fields.

## AI safety
* Crawled content is wrapped in a nonce-tagged "untrusted data" block; the page cannot close the delimiter.
* Hidden DOM text (display:none, hidden, aria-hidden) is removed before prompting.
* Structured outputs + local re-validation: unexpected fields rejected, lengths bounded, markup rejected in
  text fields, HTML fields sanitized with an allowlist (nh3), JSON-LD validated and stripped of ratings/reviews.
* "No invented facts" check rejects numbers, prices, percentages, URLs, emails and credential/award claims not
  present in the source page.
* Human approval required by default for every fix type that changes content.

## Publishing safety
Allowlisted operations only, declared per site; preflight before any state change; minimal deterministic
content edits; original state stored; independent live verification; rollback refuses to overwrite later edits.

## Billing
Stripe webhooks verified with the signing secret (timestamp tolerance), idempotent by event id, failed payments
drop entitlements to Free; dev billing mode is flagged on every record and refused in production.

## Web
Security headers (nosniff, frame deny, referrer policy, HSTS in production); exports are attachments with a
restrictive CSP; HTML reports escape all crawled content; CSV cells are protected against formula injection.

## Client IP / rate limits
Rate limits key on the client IP. Deploy behind the provided nginx config (or an equivalent load balancer) that
**overwrites** `X-Forwarded-For`, and run uvicorn with `--forwarded-allow-ips` set to the proxy's address only.
Without this, either all users share one bucket (seen as the proxy IP) or clients can spoof their IP.

## Data retention & deletion
Snapshots purged after `SNAPSHOT_RETENTION_DAYS`; anonymous audits after `ANONYMOUS_AUDIT_RETENTION_DAYS`;
expired sessions/invites cleaned up. Users can delete websites, organizations and their account (cascading deletes).

## Not yet done
Independent security review/penetration test; email verification; password reset; MFA/SSO; a Content-Security-Policy
for the Next.js app (needs nonces); malware scanning of crawled content; per-tenant encryption keys.
