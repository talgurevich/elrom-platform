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
| Takanon | `takanon` | `www.klaser.co.il` *(target: `takanon.klaser.co.il`)* | `*.onrender.com` | Tal |
| Meetings | `meetings` | *not set yet — target: `meetings.klaser.co.il`* | `*.onrender.com` | Gil |

When adding a new product, add it here first, then in `frontend/src/lib/products.ts` in every product that renders the switcher.

---

## Cookie contract

- **Name:** `klaser_session`
- **Domain:** `.klaser.co.il` (leading dot — shared across every subdomain)
- **HttpOnly, Secure, SameSite=Lax**
- **Set by:** identity service only. No product ever writes this cookie.
- **Read by:** every product's backend, forwarded to `identity/api/introspect`.

If the cookie isn't visible on your product's subdomain in DevTools after login, the switcher won't work. That's the first thing to verify.

---

## Entitlements contract

Identity's `/api/auth/me` (and `/api/introspect` for backends) returns a `entitlements: string[]` field — e.g. `["takanon", "meetings"]`. Product IDs are the same tokens listed in the registry above.

- **Frontend:** `user.entitlements` drives what shows in the switcher.
- **Backend:** every route depends on `require_entitlement("<product-id>")` (see `services/identity.py` in Takanon; Meetings has the same helper). A user without the entitlement gets 403, not 404, so the switcher can still route them home.

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
4. Current product renders as a **disabled label with a "•" marker**, not a link.
5. Other products render as `<a href="https://<host>/">`. Full-page navigation is correct — no SPA routing across subdomains.
6. If the user has only one entitlement, don't render the switcher section at all (avoid empty ceremony).

Reference implementation lives in Takanon at `frontend/src/App.tsx` (user menu) + `frontend/src/lib/products.ts`. Copy it into Meetings verbatim; the only change per product is which `id` you pass as `currentProductId`.

---

## Adding a subdomain (Render + DNS)

Do this once per product frontend. Backends can stay on `*.onrender.com` — users never see them.

1. In Render → the frontend static site → **Settings → Custom Domains → Add**. Enter e.g. `meetings.klaser.co.il`.
2. Render displays a **CNAME target** like `xyz.onrender.com` (and sometimes a TXT verification record).
3. In the DNS registrar (My Names, currently) add: **CNAME `meetings` → `<render-target>`**. TTL default is fine.
4. Wait 2–15 min. Render auto-issues an SSL cert via Let's Encrypt once DNS resolves.
5. Set env vars on the product's **backend**:
   - `KLASER_APP_URL=https://<new-host>` (used for magic-link and RSVP emails, etc.)
   - Add `https://<new-host>` to the CORS allowlist.
6. Set env var on the product's **frontend** (if applicable):
   - `VITE_API_URL` unchanged (still the Render backend host)
   - Rebuild + redeploy.
7. Verify in DevTools that the `klaser_session` cookie is visible on the new host after login.

---

## CORS

Each product backend must include the peer product frontends in its CORS `allow_origins` only if that peer will make cross-origin calls to it. For the switcher itself, no cross-origin calls happen — the switcher is plain `<a href="...">` navigation, cookie carries the auth. Keep CORS narrow.

---

## What Meetings needs to add (checklist for Gil)

1. Custom domain `meetings.klaser.co.il` on the frontend static site (steps above).
2. `KLASER_APP_URL=https://meetings.klaser.co.il` on the Meetings backend.
3. Verify the `klaser_session` cookie is present on `meetings.klaser.co.il` after login. If it isn't, identity's cookie is scoped too narrowly — flag to Tal.
4. Copy `frontend/src/lib/products.ts` from Takanon; set `currentProductId = "meetings"` when rendering the switcher.
5. Render the switcher in the user dropdown, above logout — same slot, same visual weight as Takanon.
