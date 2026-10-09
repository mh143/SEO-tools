# API

Base path: `/api`. Interactive OpenAPI docs: `/api/docs` (JSON at `/api/openapi.json`).

Authentication: session cookie `rl_session` (HttpOnly, SameSite=Lax) set by `/auth/signup` or `/auth/login`.
Unsafe methods (POST/PUT/PATCH/DELETE) require header `X-CSRF-Token` equal to the `rl_csrf` cookie / the
`csrf_token` returned at login. Errors: `{"detail": ...}`; plan limits return **402** with
`{"detail": {"code": "plan_limit" | "feature_unavailable", "message": ...}}`. Non-members get **404** for
another organization's resources; insufficient role gives **403**.

Roles: viewer < editor < admin < owner.

## Public
| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/health/ready` | liveness / readiness (DB + Redis) |
| GET | `/public/plans` | plan catalogue (CAD) and billing mode |
| POST | `/public/audits` `{url}` | anonymous quick audit (≤10 pages, rate limited) → `{token}` |
| GET | `/public/audits/{token}` | status, scores, findings |
| GET | `/public/audits/{token}/export?format=csv|json|md|html` | download |
| GET | `/integrations/providers` | available / not-yet-implemented connectors |
| POST | `/billing/webhook` | Stripe webhook (signature verified, idempotent) |

## Auth
`POST /auth/signup {email,password,name?,org_name?,invite_token?}` · `POST /auth/login` · `POST /auth/logout` ·
`GET /auth/me` · `POST /auth/password {current_password,new_password}` · `POST /auth/invitations/accept {token}` ·
`POST /auth/delete-account {password}`

## Organizations & team
| Method | Path | Role |
|---|---|---|
| POST | `/orgs {name}` | any user |
| GET/PATCH/DELETE | `/orgs/{org}` | viewer / admin / owner |
| GET | `/orgs/{org}/overview` | viewer |
| POST | `/orgs/{org}/notifications/read` | viewer |
| GET | `/orgs/{org}/members` | viewer |
| POST | `/orgs/{org}/invitations {email,role}` → `{invite_url}` | admin |
| DELETE | `/orgs/{org}/invitations/{id}` | admin |
| PATCH/DELETE | `/orgs/{org}/members/{membership_id}` | admin (self may leave) |
| GET | `/orgs/{org}/audit-logs` | admin |

## Websites, crawls, issues, pages
| Method | Path | Role |
|---|---|---|
| GET/POST | `/orgs/{org}/websites` (`{url,name?}`) | viewer / editor |
| GET/PATCH/DELETE | `/orgs/{org}/websites/{id}` (`{name?, schedule?: none|daily|weekly|monthly, crawl_settings?}`) | viewer / editor / admin |
| GET/POST | `/orgs/{org}/websites/{id}/crawls` (`{max_pages?,max_depth?,render_js?}`) | viewer / editor |
| GET | `/orgs/{org}/crawls/{id}` | viewer |
| POST | `/orgs/{org}/crawls/{id}/cancel` | editor |
| GET | `/orgs/{org}/crawls/{id}/issues?category&severity&finding_type&status&rule_id&url&q&limit&offset` | viewer |
| GET | `/orgs/{org}/crawls/{id}/pages?q&status_class&limit&offset` | viewer |
| GET | `/orgs/{org}/crawls/{id}/export?format=csv|json|md|html` | viewer |
| GET | `/orgs/{org}/pages/{id}`, `/orgs/{org}/pages/{id}/snapshot` | viewer |
| GET/PATCH | `/orgs/{org}/issues/{id}` (`{status: open|ignored}`) | viewer / editor |

## Fixes
| Method | Path | Role |
|---|---|---|
| POST | `/orgs/{org}/issues/{id}/fixes` | editor (AI fixes consume `ai_requests`) |
| GET | `/orgs/{org}/fixes?status=a,b&website_id&fix_type` | viewer |
| GET/PATCH | `/orgs/{org}/fixes/{id}` (`{after: {...editable fields}}`) | viewer / editor |
| POST | `/orgs/{org}/fixes/{id}/submit` | editor |
| POST | `/orgs/{org}/fixes/{id}/approve`, `/reject {reason}` | admin |
| POST | `/orgs/{org}/fixes/{id}/apply` | admin (preflight; consumes `publish_ops`) |
| POST | `/orgs/{org}/fixes/{id}/mark-applied` | editor (then verified on live site) |
| POST | `/orgs/{org}/fixes/{id}/verify` | editor |
| POST | `/orgs/{org}/fixes/{id}/rollback` | admin |
| GET | `/orgs/{org}/fixes/{id}/export?format=txt|json`, `/orgs/{org}/fixes-export?format=json|csv` | viewer |
| GET | `/orgs/{org}/changes?website_id` | viewer |

## Integrations
`GET /orgs/{org}/integrations` · `POST /orgs/{org}/integrations/wordpress/start {website_id}` → `{authorization_url}` ·
`GET /integrations/wordpress/callback` (browser redirect from WordPress) ·
`POST /orgs/{org}/integrations/wordpress/manual {website_id, username, application_password}` ·
`POST /orgs/{org}/integrations/{id}/refresh` · `DELETE /orgs/{org}/integrations/{id}` (all admin).
Credentials are never returned.

## Keywords
`GET /orgs/{org}/websites/{id}/keywords` · `POST .../keywords/research {seeds[], location, language}` (DataForSEO) ·
`POST .../keywords/ideas` (AI, unmeasured) · `POST .../keywords/on-page` · `DELETE /orgs/{org}/keywords/{id}`

## Billing
`GET /orgs/{org}/billing` · `POST /orgs/{org}/billing/checkout {plan_key}` (owner; Stripe Checkout URL or
simulated change in dev mode) · `POST /orgs/{org}/billing/portal` · `POST /orgs/{org}/billing/cancel` ·
`POST /orgs/{org}/billing/dev/simulate-payment-failure` (dev mode only)

## Admin (platform admins only; others get 404)
`GET /admin/overview` · `/admin/organizations?q` · `/admin/users?q` · `POST /admin/users/{id}/active?active=bool` ·
`/admin/crawls?status` · `/admin/webhooks` · `/admin/audit-logs?action`
