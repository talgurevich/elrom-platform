# Billing Setup — Services Requiring a Credit Card

All services below are currently on free tiers or trial credits. To run a production design-partner pilot, each one needs a real card on file.

## Hosting & Infrastructure

### Render — https://render.com
**What it's for:** Hosts everything. Runs the Python backend API, serves the React frontend as a static site, and provides the managed Postgres database that stores tenants, documents, chunks, and embeddings. This is where the product literally lives on the internet.

- **Current state:** Free tier (all three services).
- **Free-tier limits:** Dynos sleep after 15 min of inactivity (≈30s cold start). Postgres free tier capped at 1 GB and expires after 90 days.
- **Recommended plan:** Starter, ~$7/mo per service. Total ≈ **$21/mo** (backend + frontend + DB) to keep everything always-on.
- **Priority:** High — cold starts are visible to users during demos, and free Postgres expiring means we lose all data.

## AI / LLM APIs

All pay-as-you-go, no monthly minimum. Spend scales with usage.

### Anthropic — https://console.anthropic.com
**What it's for:** The brain of the product. Claude **Sonnet 4.6** generates the actual answers users see (Hebrew Q&A with citations from kibbutz/cooperative documents). Claude **Haiku 4.5** runs cheaper background tasks like extracting structured fields from uploaded documents.

- **Budget estimate:** $50–200/mo at pilot scale. **Main cost driver of the system.**
- **Priority:** Highest.

### Cohere — https://dashboard.cohere.com
**What it's for:** Converts every document chunk and every user query into vector embeddings (`embed-multilingual-v3.0`), which is how the system finds the right passages to answer a question. Cohere is the primary embedding provider because it handles Hebrew well.

- **Budget estimate:** Low (<$20/mo at pilot scale).
- **Priority:** Medium — trial credits will eventually run out.

### OpenAI — https://platform.openai.com
**What it's for:** Backup embedding provider (`text-embedding-3-large`). Used as a fallback if Cohere is unavailable, and kept around so we can swap providers without code changes.

- **Budget estimate:** Low (<$10/mo at pilot scale).
- **Priority:** Medium — trial credits will eventually run out.

## Document OCR

### Azure Document Intelligence — https://portal.azure.com
**What it's for:** Extracts text from scanned Hebrew PDFs (the kind that come from fax machines, photocopies, and old archives — where the PDF is really just an image, not selectable text). Without this, scanned cooperative-society documents are unreadable to the system. Pay-per-page.

- **Current endpoint region:** Qatar Central (chosen for Hebrew support + EU-adjacent latency).
- **Budget estimate:** Depends entirely on document volume.
- **Priority:** High — OCR is core to the product. Most real customer documents are scanned.

## Email

### Resend — https://resend.com
**What it's for:** Sending transactional email — primarily the magic-link login flow (the user enters their email, we send them a one-click sign-in link). Also used for system notifications later.

- **Plan:** Paid (Pro tier, ~$20/mo for 50k emails) — needed for a custom sending domain (`@elrom.tv`) and higher deliverability, which matter for the design-partner pilot.
- **Current state:** API key not yet configured (`RESEND_API_KEY` is empty). Auth flow not yet wired up in code.
- **Priority:** Medium — set up the billing now so the domain verification + DNS records are ready when auth ships.

## Not Needed (No Card)

- **GitHub** — public repo on free plan is sufficient for now.

## Recommended Setup Priority

1. **Anthropic** — highest spend, immediate need.
2. **Azure Document Intelligence** — core product functionality (OCR).
3. **Render Starter upgrade** — eliminates cold starts during demos, preserves the database.
4. **Resend Pro** — needed for a verified `@elrom.tv` sender domain before auth ships.
5. **Cohere + OpenAI** — low spend, but trial credits expire.
