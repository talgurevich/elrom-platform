# Klaser platform — infrastructure plan

**TL;DR.** Three independent services, one shared identity. Each product deploys on its own cadence; login and tenants live in a dedicated identity service.

## The three services

| Service | Repo | Frontend URL | Backend URL | Postgres | Owner |
|---|---|---|---|---|---|
| **Identity** | `klaser-identity` (new) | `auth.klaser.co.il` (login/register pages) | same host, `/api/*` | identity DB (users, tenants, sessions, subscriptions, tokens) | Tal |
| **Takanon** | `elrom-platform` (rename later to `klaser-takanon`) | `takanon.klaser.co.il` | `api.takanon.klaser.co.il` | takanon DB (docs, chunks, lexicon, amendments, goldens) | Tal |
| **Klaser Meetings** | `klaser-meetings` (new) | `meetings.klaser.co.il` | `api.meetings.klaser.co.il` | meetings DB (recordings, transcripts, protocols) | Gil |

## How auth flows

1. User visits `takanon.klaser.co.il` (or `meetings.klaser.co.il`).
2. Frontend checks for a session cookie scoped to `.klaser.co.il`. If missing → redirect to `auth.klaser.co.il/login?redirect=…`.
3. Identity handles Google OAuth (single client) or email+password login, sets the session cookie on `.klaser.co.il`, redirects back.
4. Product frontend now has the cookie. Every API call to its backend includes it.
5. Product backend calls `auth.klaser.co.il/api/me` with the cookie → gets `{ user, tenant, entitlements: ["takanon", "meetings"] }`.
6. Product backend verifies its entitlement is in the list → serves the request, or 403s.

## What lives where (data ownership rule)

- **Identity DB** owns: `users`, `tenants`, `user_tenants`, `subscriptions`, `auth_tokens`, `sessions`. **Nothing else.**
- **Takanon DB** owns: everything doc-related. Foreign keys to users/tenants are just UUIDs — no `JOIN`s across DBs. Enrich by calling the identity API when needed.
- **Meetings DB** owns: everything meeting-related. Same rule.

## Product switcher

Each product's header renders a switcher from `me.entitlements`:
- `["takanon"]` → no switcher.
- `["takanon", "meetings"]` → switcher with both, current one highlighted, click deep-links to the other frontend.

## Google OAuth setup

- **One** OAuth client in Google Cloud.
- **One** authorized redirect URI: `https://auth.klaser.co.il/api/auth/google/callback`.
- Products never touch the OAuth callback themselves.

## Service-to-service calls

Each product backend gets a **service token** (long-lived, per-product secret) so it can call the identity service for user lookups outside a request context (background jobs, cron, admin scripts). Passed as `Authorization: Bearer <service-token>`.

## Order Gil should assume

1. **Tal ships `klaser-identity` first** — port auth routes from Takanon, migrate users/tenants data over, cut Takanon over to call identity, widen the cookie to `.klaser.co.il`. ~1 week of Tal's time.
2. **Gil starts `klaser-meetings`** against the already-live identity service. No temporary local auth in Meetings, ever.
3. If timing forces Gil to start before identity is up: stub the auth SDK with a fake user in dev and swap to real calls when identity ships. **Do not add a users table to Meetings.**

## Render layout

- One Render project per service (three total).
- Frontends: static-site services.
- Backends: web services.
- Databases: three separate managed Postgres instances (cheapest tier is fine for identity — small data, low traffic).
- DNS on the same domain (`klaser.co.il`) so the parent-domain cookie works.

## Cost delta

Roughly a third Render web service + a third Postgres vs the "identity lives inside Takanon" alternative. ~$20–30/month extra. Cheap compared to a future migration.

## What Gil owns end-to-end vs shares

- **Owns**: everything in `klaser-meetings` (frontend, backend, DB, deploy pipeline, product decisions).
- **Consumes**: the identity API — treat it as a black-box HTTP contract. Never reach into its DB.
- **Coordinates with Talia**: on the shared design system (npm package or copy-paste at first).
- **Coordinates with Tal**: on the entitlements model (which product IDs, which plans) and any changes needed to the identity API contract.
