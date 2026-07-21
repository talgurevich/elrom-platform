# Klaser portfolio — cross-product integration

**Audience:** anyone building a product that plugs into the Klaser suite (currently Tal on Takanon, Gil on Meetings, whoever comes next).
**Purpose:** the concrete contract for wiring a product into the platform — cookie, entitlements, switcher, domains. Not a plan, a reference. Update in place as reality changes.

Related:
- [`klaser-platform-infra.md`](./klaser-platform-infra.md) — the original architecture plan (three services, one identity).
- [`identity-cutover.md`](./identity-cutover.md) — how Takanon moved off local auth onto the shared identity service.

---

## Product registry

| Product | ID (entitlement) | Frontend host | Backend host | Owner |
|---|---|---|---|---|
| Identity | *n/a — the identity service itself* | `auth.klaser.co.il` | same host, `/api/*` | Tal |
| Takanon | `takanon` | `takanon.klaser.co.il` (also served on `www.klaser.co.il` during migration) | `*.onrender.com` | Tal |
| Meetings | `meetings` | `meetings.klaser.co.il` (live) | `api.meetings.klaser.co.il` | Gil |

When adding a new product, add it here first, then in `frontend/src/lib/products.ts` in every product that renders the switcher.

---

## Cookie contract

- **Name:** `klaser_session`
- **Domain:** `.klaser.co.il` (leading dot — shared across every subdomain) ✅ verified 2026-07-19
- **HttpOnly, Secure, SameSite=None** (Secure=true makes SameSite=None valid; Lax would also work but current setting is None)
- **Set by:** identity service only. No product ever writes this cookie.
- **Read by:** every product's backend, forwarded to `identity/api/introspect`.

Gil doesn't need to re-verify — the cookie was confirmed cross-subdomain-shared on 2026-07-19. If it ever stops working on a new subdomain, DevTools → Application → Cookies is the first place to look.

---

## Entitlements contract

Identity's `/api/auth/me` (and `/api/introspect` for backends) returns an `entitlements: string[]` field — e.g. `["takanon", "meetings"]`. Product IDs are the same tokens listed in the registry above. ✅ verified 2026-07-19.

- **Frontend:** `user.entitlements` drives what shows in the switcher. Your `CurrentUser` type needs `entitlements?: string[]`.
- **Backend:** every route depends on `require_entitlement("<product-id>")` (see `services/identity.py` in Takanon; Meetings already has the same helper). A user without the entitlement gets 403, not 404, so the switcher can still route them home.

### Granting / revoking (super-admin)

Managed via the **Takanon Admin panel → per-tenant "מוצרים" section** (interim home — will move into an identity admin surface eventually). Under the hood:

- `POST /api/service/tenants/{id}/subscriptions` on identity, idempotent — reactivates an existing row rather than duplicating.
- `DELETE /api/service/subscriptions/{id}` on identity — hard-delete.

Effect is immediate on the *next* request; identity is not cached at the entitlement level. The user needs to reload for the frontend switcher to update.

---

## Product switcher — UX contract

Every product renders the switcher in the same slot: **inside the user dropdown, above "התנתקות" (logout)**. Same visual weight, same order across products, so switching feels native.

Rules:
1. Read `user.entitlements` from the auth context.
2. Iterate the products registry (`frontend/src/lib/products.ts`).
3. Render one row per entitled product.
4. Current product renders as a **plain label with a "• פעיל" marker**, not a link.
5. Other products render as `<a href="https://<host>/">`. Full-page navigation is correct — no SPA routing across subdomains.
6. If the user is entitled to fewer than two products, don't render the switcher section at all (avoid empty ceremony).

**Reference implementation** in Takanon:
- `frontend/src/lib/products.ts` — the registry + `CURRENT_PRODUCT_ID`. Copy this file verbatim into Meetings; change `CURRENT_PRODUCT_ID` to `"meetings"`.
- `frontend/src/App.tsx` — the switcher block inside the user dropdown (search for `מעבר בין מוצרים`). Copy the JSX; adjust to match Meetings' auth context shape.
- `frontend/src/lib/api.ts` — add `entitlements?: string[]` to `CurrentUser`.

To see the switcher render locally during development, grant your test tenant a second product via the Takanon Admin panel → tenant → "מוצרים" section.

---

## Adding a subdomain (Render + DNS)

Do this once per product frontend **and once per product backend**. Backends **cannot** stay on `*.onrender.com`: the `klaser_session` cookie is scoped to `.klaser.co.il`, and the browser never attaches it to a request host outside that domain (CORS `credentials: include` does not override this). A backend on a raw `*.onrender.com` URL silently 401s "Not authenticated". Every backend must therefore also get an `api.<product>.klaser.co.il` custom domain — add it the same way (Render → the *backend* web service → Custom Domains → Add).

1. In Render → the frontend static site → **Settings → Custom Domains → Add**. Enter e.g. `meetings.klaser.co.il`.
2. Render displays a **CNAME target** like `xyz.onrender.com` (and sometimes a TXT verification record).
3. In the DNS registrar (My Names, currently) add: **CNAME `meetings` → `<render-target>`**. TTL default is fine.
4. Wait 2–15 min. Render auto-issues an SSL cert via Let's Encrypt once DNS resolves.
5. Set env vars on the product's **backend**:
   - `KLASER_APP_URL=https://<new-host>` (used for magic-link and RSVP emails, etc.)
   - Add `https://<new-host>` to the CORS allowlist.
6. Set env var on the product's **frontend**:
   - Point the API base env var at the backend's `api.<product>.klaser.co.il` host — **not** its raw `*.onrender.com` URL (see cookie note above). In Meetings this var is `VITE_API_BASE_URL`.
   - Rebuild + redeploy — Vite bakes env vars in at build time, so a restart alone won't pick up the change.
7. Verify in DevTools that the `klaser_session` cookie is visible on the new host after login.

---

## CORS

Each product backend must include the peer product frontends in its CORS `allow_origins` only if that peer will make cross-origin calls to it. For the switcher itself, no cross-origin calls happen — the switcher is plain `<a href="...">` navigation, cookie carries the auth. Keep CORS narrow.

---

## What Meetings needs to add (checklist for Gil)

Prereqs already handled by Tal — you don't need to redo them:
- Identity cookie is `.klaser.co.il`-scoped ✅
- Identity `/api/auth/me` returns `entitlements` ✅
- Identity has `POST/DELETE` service endpoints for subscriptions ✅
- Takanon Admin can grant `meetings` to any tenant ✅

Your side:
1. **Deploy Meetings on Render** if you haven't yet (backend web service + frontend static site + Postgres). Model `render.yaml` on Takanon's if useful — happy to prep one against your repo, just ask.
2. **Custom domains** — add *both*: `meetings.klaser.co.il` on the frontend static site **and** `api.meetings.klaser.co.il` on the backend web service (the backend domain is mandatory — the session cookie won't attach to a raw `*.onrender.com` host). Render → Settings → Custom Domains → Add on each. Paste the CNAME targets back to Tal, who'll add the DNS records at My Names.
3. **Backend env vars**: set `KLASER_APP_URL=https://meetings.klaser.co.il` (for RSVP + invite emails).
   Then point the frontend's `VITE_API_BASE_URL` at `https://api.meetings.klaser.co.il` and redeploy (Vite bakes env at build time).
4. **Frontend types**: add `entitlements?: string[]` to your `CurrentUser` type.
5. **Copy** `frontend/src/lib/products.ts` from Takanon **verbatim**, then set `CURRENT_PRODUCT_ID = "meetings"`.
6. **Render the switcher** in the user dropdown, above logout — copy the JSX block from Takanon's `frontend/src/App.tsx` (search "מעבר בין מוצרים"). Filter `PRODUCTS` by `user.entitlements`.
7. **Verify** end-to-end: log in on `meetings.klaser.co.il`, grant your test tenant both `takanon` and `meetings` via the Takanon Admin panel, reload, open the user menu → you should see both products with "ישיבות" marked as active.

**Debug**: if entitlements is missing from your `/me` response, you may be hitting the wrong host — `authRequest` should target `IDENTITY_BASE` (`https://auth.klaser.co.il`), not your product backend. See Takanon's `frontend/src/lib/api.ts` for the split between `request()` and `authRequest()`.
