# Roadmap → v0.3

> Last updated: 2026-06-21. Load this into context next session.
> The original spec lives in `SPEC.md` — this doc supersedes its roadmap section,
> which is out of date as of v0.2.

---

## Where we are: v0.2 (shipped, in prod on Render Standard)

### Ingest quality (was the original v0.2 focus)
- **Loud-fail OCR**: partial-batch failures raise `PartialOcrError` instead of silently persisting fragments.
- **Extraction telemetry** persisted per document: `extractor / used_ocr / pages / chars_extracted / chunks_created / extraction_partial / extraction_note`.
- **Density gate** (`chars/page < 200` → 400) blocks bad ingests.
- **Reversed-Hebrew detection** auto-routes pdfplumber-fed garbage through Azure OCR.
- **Force-OCR default for PDFs** in `/ingest/upload`.
- **Auto-classify after upload** (background task) — gives docs a Hebrew title, doc_type, summary, and folder. No button.
- **Quality badges in UI**: ✓ תקין / ⚠ חלקי / ⚠ דליל / ⚠ ללא קטעים / ? ישן.
- **Bulk delete** with double-confirm.

### Retrieval quality
- **Contextual embeddings** — chunk text is prepended with `<doc title> — <section_path>` before embedding. Verified end-to-end: `"מה אומר סעיף 4.1 בתקנון פנסיה?"` now hits the exact section.
- `scripts/reembed_contextual.py` for in-place reindex of an existing corpus.
- `_reembed_document_chunks` runs automatically when the classifier renames a doc to a real Hebrew title.

### Search UX
- **Server-Sent Events progress** — `/api/search/stream` emits `stage / detail / done` events. Bar advances on real server events; eased fill within a stage avoids dead air.
- **HowItWorks** explainer card on the virgin Search page.
- **Recently-asked questions** list — one click to re-ask.
- **Share actions** after every answer: WhatsApp / Email / Copy as Markdown / Copy as plain text. Footer = "Powered by זכרון ארגוני".
- **Retire-on-thumbs-down** for cache-served answers + automatic re-search.

### Multi-tenancy
- Real tenant scoping: every endpoint requires `current_user`; every by-id route filters by `tenant_id` and 404s cross-tenant access.
- `scripts/create_tenant.py` and `scripts/add_user.py` for onboarding.
- **Super-admin** (read-only cross-tenant inspector) — `users.is_super_admin` flag, session-level `viewing_tenant_id`, middleware enforces a tiny write whitelist (search + feedback + auth). Granted via `scripts/grant_super_admin.py`. UI = tenant-switcher dropdown in the wordmark + persistent accent banner while viewing.

### Documents library
- Toolbar: search box + sort (recent / א–ת / chunks) + group (none / type / folder) + type filter chips + folder filter chips.
- **AI auto-folders** — flat, single-membership, classifier-assigned. Existing folder names passed back to the model to avoid synonym drift.

### UI
- Modernist redesign across every page: heavy Heebo display type, clay-red accent (#b8412b), hairline borders over soft shadows, sharper corners. No more SaaS template look.
- Consistent page-header pattern: small accent eyebrow + h1 + supporting paragraph.
- **Wordmark follows tenant** — driven by `user.tenant_name` from `/auth/me`. Login uses product name "זיכרון ארגוני".
- **Neural-mesh SVG background** on Login (pure SVG, no asset).
- **Footer** on every page: copyright / support email / GitHub commits feed / version.

### Operations
- On Render **Standard tier** (2 GB RAM, 2 workers).
- All blocking work in routes wrapped in `asyncio.to_thread` so `/api/health` survives long OCR / LLM calls.
- Embedding calls batched to respect Cohere's 96-text cap.

---

## Loose ends (do these before / alongside v0.3 work)

1. **Backfill folder values on prod's existing 25 docs** — open Upload page → "סווג הכל מחדש". One click, ~2-4 min.
2. **Create the super-admin user on prod** — Render shell:
   ```bash
   python -m scripts.add_user --tenant-name "אלרום" \
     --email tal.gurevich@gmail.com --role admin --name "Tal Gurevich"
   python -m scripts.grant_super_admin --email tal.gurevich@gmail.com
   ```

---

## v0.3 — proposed scope

The version-label theme: **"the retrieval pass we were supposed to ship as v0.2."**
All the items below are real recall/precision wins, not polish.

### Tier 1 — the highest-ROI items

1. **Hebrew-aware BM25** *(the "wall" memory)*
   - `to_tsvector('simple', …)` returns 0 hits on real Hebrew queries because of prefix attachment (ה/ב/ל/ש/ו/מ/כ) and pronoun suffixes (יו/ה/ם).
   - Fix options ranked by simplicity:
     a. Python-side prefix stripping before query/index (~30 lines, recovers 80% of recall, no new dep).
     b. Install a Hebrew dictionary for Postgres FTS (`hspell` or similar — needs system packages on the Render image).
     c. Stem in Python with a Hebrew morphology lib (heavier, more flexible).
   - Vector alone is carrying retrieval today. Until this lands, the hybrid pipeline isn't really hybrid.
   - See memory: `project_bm25_hebrew_gap.md`.

2. **Golden set + baselines**
   - The "קבע כשאלת זהב" endpoint works but no actual set has been built.
   - Need ~20 Q's with `expected_doc_filenames` + `expected_keywords` covering the corpus's main topics.
   - Run baseline eval *before* any retrieval change in v0.3 so each change can be scored, not vibes-checked.
   - The Hebrew BM25 fix should be the first measured improvement.

### Tier 2 — solid wins, do after Tier 1

3. **Hierarchical section_path** (chunking Gap 2 from the earlier analysis)
   - Today `section_path = "4.1"`. Store `"פרק ג > 4.1"` instead — clearer citations + better rerank signal.
   - ~30 lines in `chunking.py` + a one-shot rebuild of the corpus.

4. **TOC filtering** (chunking Gap 3)
   - Detect table-of-contents pages, drop them or downweight them. ~15-20% of the corpus is currently noise.

5. **Lexicon-driven query rewriting**
   - When a lexicon term matches the user's question, expand it *into the embedding query*, not just the LLM prompt. Today the lexicon is explained to Claude but vector search still uses the unexpanded form.

### Tier 3 — bigger experiments, do if Tier 1+2 don't close the gap

6. **HyDE** — generate a hypothetical answer with Haiku, embed it, retrieve against that. A/B vs baseline on the golden set; ship if it wins.
7. **Multi-query fan-out** — Haiku rewrites the question 3 ways, retrieve for each, RRF-fuse. Same A/B treatment.

### Operational (slot in opportunistically)
8. **Pytest coverage for tenant isolation** — prove tenant A can't see tenant B's data via any endpoint. The code is correct, just unverified.
9. **Magic-link login alongside Google** (Resend Pro slot exists in env vars; flow doesn't).
10. **Per-tenant cost dashboard** — queries / month, LLM cost, cache hit rate, top failed queries.

---

## Deferred (v0.4+)

### v0.4 — HITL workflow
- Bulk approve/reject + keyboard shortcuts (A / R / E / J / K).
- Diff view: LLM original vs reviewer-edited, git-style highlighting.
- Authoritative-answer versioning: retire/replace when a bylaw changes.
- Auto-suggest authoritative when reviewer opens a query.
- Reviewer analytics: top-failure docs, weekly digest.

### v0.5 — Generation quality
- Eval-driven prompt iteration loop (every prompt change scored on the golden set).
- Answer-length awareness (yes/no → 1 sentence; "what is X" → 2 paragraphs; "what's the process" → numbered list).
- Self-consistency for high-stakes questions (run twice with different chunk orderings, return consensus).
- Inline-citation hover tooltips on the frontend.

### v1.0 — polish + accessibility
- Mobile responsive layout.
- **Israeli accessibility compliance** — IS 5568 + WCAG 2.1 AA Hebrew RTL (mandatory under the Equal Rights for Persons with Disabilities Act in Israel; non-compliance carries fines).
- Search history (per-user) + bookmarked answers.
- Shareable answer links (`/answer/<query_id>`).
- Document thumbnails.
- Light/dark theme.
- Notification system.

### Backlog (post-v1.0)
- Slack / WhatsApp bot integration.
- Mobile native (React Native — frontend is already TS).
- Cross-tenant anonymized analytics ("90% of kibbutzim asked X this quarter").
- Read-only public knowledge pages (per-tenant, opt-in).
- Embeddable "ask a question" widget for the kibbutz's own website.

---

## Recommended v0.3 order

1. Press the two prod backfill buttons (5 min).
2. Build the golden set + baseline scores (1-2 hours).
3. Hebrew BM25 fix — option (a), the prefix-stripping one. Measure the delta. (1 hour + measurement).
4. Hierarchical section_path + TOC filtering as a single chunking pass + re-embed. Measure. (2-3 hours).
5. Stop at "v0.3 shipped" — ship a release note, sit with it, see what falls out before moving to Tier 3 experiments.

If after step 4 the golden-set scores are unsatisfying, do HyDE or multi-query next. If they're satisfying, jump to v0.4 reviewer workflow.

---

## State references (load alongside this doc)

- `SPEC.md` / `SPEC.html` — original v0.1 spec; roadmap section is stale.
- `RELEASE-0.2.html` — release notes you can forward.
- Latest commit: `e1ba6d5` (neural-mesh login).
- Live: `elrom-frontend.onrender.com` → `elrom-backend.onrender.com`.
- Tenant in prod: **אלרום** (renamed via SQL after CLI seeded it as "קיבוץ רביבים (dev)").
- Existing users in prod: `tal.gurevich2@gmail.com`, `noam-elrom`-related, `moti.yair@elrom.tv`. Pending: `tal.gurevich@gmail.com` (super-admin).
