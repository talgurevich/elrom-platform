# Elrom Platform — Specification

> Status: v0.1 MVP shipped (June 2026). Document is current as of v0.1; roadmap below.

---

## 1. Goal

**The problem.** Kibbutz and moshav secretariats hold decades of bylaws, sub-bylaws, board protocols, assembly decisions, and policy memos. Members ask the secretary questions like *"What happens to my father's house and equity units after he died?"* every week — and the secretary has to read through 14 documents to answer. Generic AI tools (ChatGPT, NotebookLM) can ingest the documents but don't understand the **hierarchy** (sub-bylaw overrides main bylaw), the **terminology** (`בן נסמך` is not "an heir"), or the **organizational memory** (which decisions are still active vs. retired).

**What Elrom does.** A per-tenant search-and-answer system over the kibbutz's own corpus, with three things generic tools don't have:

1. A **structured citation layer** — every answer cites bylaw + section + verbatim excerpt.
2. A **human-in-the-loop authoritative-answer cache** — once a reviewer approves an answer, future similar questions return that answer verbatim (no LLM call, no drift).
3. A **per-tenant lexicon** — domain terms that route the LLM around predictable mistakes.

**Why now.** Hebrew-capable LLMs (Claude Sonnet 4.6) are finally good enough; multilingual embeddings (Cohere v3) finally rank Hebrew well; Azure DI finally OCRs scanned Hebrew bylaws correctly. Two years ago this didn't work.

**Who it's for, today.** Design-partner secretariats of kibbutzim and moshavim in Israel. The seed customer is קיבוץ אל-רום.

**Who it's for, eventually.** Any cooperative organization with a deep document corpus and a "ask the secretary" workflow — kibbutzim, moshavim, professional associations, religious communities, condo associations.

---

## 2. Success metrics

### Product quality (the ones we ship against)

| Metric | Definition | Target |
|---|---|---|
| **Answer precision** | % of `confident` answers a reviewer approves without edits | ≥ 80% |
| **Retrieval recall** | % of golden questions where every required doc appears in top-5 | ≥ 90% |
| **Answer brevity** | Mean answer length on yes/no questions | ≤ 200 chars |
| **HITL cache hit rate** | % of queries served from authoritative cache (LLM bypassed) | grows weekly |
| **Reviewer load** | Mean reviewer minutes per approved authoritative answer | ≤ 2 min |

All measurable via `POST /api/eval/run` against the golden set.

### Operational (the ones we watch)

| Metric | Target |
|---|---|
| **p95 query latency** (LLM path) | ≤ 12s |
| **p95 query latency** (HITL cache hit) | ≤ 1.5s |
| **Cost per query** (LLM path) | ≤ $0.02 |
| **Cost per query** (cache hit) | ≤ $0.0005 |
| **MAU per tenant** | tracked, no target until we have 3+ tenants |

---

## 3. How the portal works

A member or staff person opens the web app, signs in with Google, and lands on the search tab.

**Asking a question.** They type a question in Hebrew. While the request is in flight, the UI cycles through pipeline stages (`🔎 מנתח את השאלה → 📚 מחפש בארכיון → 🎯 מדרג מקורות → ✍️ מנסח תשובה`) so they know what's happening. Total wait: 5–15 seconds end-to-end.

**The answer.** They see, top to bottom:
1. **Confidence chip** — `תשובה מבוססת`, `תשובה חלקית`, or `אין תשובה במאגר`.
2. **Cited clauses** — each one shows the bylaw name, section number, source type, and a verbatim excerpt.
3. **Natural-language answer** — short, direct, opens with the rule for yes/no questions.
4. **Feedback row** — 👍 / 👎 / "promote to golden question."
5. **Raw retrieved chunks** (collapsible, for debugging) and **retrieval debug panel** showing per-stage scores.

**If a near-miss authoritative answer exists** for this question (similarity 0.82–0.92 to something previously approved), it's surfaced *above* the LLM answer with a warning so the user can rebase or the reviewer can avoid creating duplicates.

**Tagging failures.** If the user gives 👎, a tagger appears: *retrieval miss, wrong generation, other*. This is the data the eval loop runs on later.

**Reviewer workflow.** The reviewer opens the תור בדיקה tab, sees recent queries (negative-feedback first), and for each one can: approve as-is, edit and approve (promoted to the HITL cache), reject, or **retry** (re-runs the question against the current pipeline so you can see if a prompt/embedding change improved it).

**Document management.** Upload PDFs/DOCX/TXT; PDFs route to Azure DI OCR if pdfplumber returns no text. Each document is auto-classified by Claude Haiku — title, type (bylaw / sub-bylaw / minutes / decision / other), one-line summary. Hash-named files from scanned-source URLs get human-readable titles assigned.

**Eval.** A separate `הערכה` tab holds golden questions. One-click "Run eval" re-issues every golden through the live pipeline and scores it: retrieval recall (did the required docs surface?), keyword recall (did the required terms appear in the answer?), composite. Per-question scores persist for delta tracking after any change.

**Lexicon.** A `מילון` tab holds tenant-specific term expansions. There's also a "✨ suggest entries" button that sweeps recent failed queries with Claude Haiku and proposes new entries.

---

## 4. Stack

| Layer | Choice | Why |
|---|---|---|
| Hosting | **Render** (frankfurt) | Cheapest with a GitHub-app webhook, blueprint deploys, managed Postgres in EU. |
| Database | **Postgres 16 + pgvector** | One database for relational data and vector embeddings — no separate vector store to operate. |
| Backend | **Python 3.11 + FastAPI + SQLAlchemy 2 + Alembic** | Mature async-friendly stack, the AI ecosystem is Python-native. |
| Frontend | **React 18 + Vite + TypeScript + Tailwind 3** | Small footprint, RTL works out of the box, fast HMR. |
| Auth | **Google OAuth (Identity Services)** + Starlette `SessionMiddleware` | Invite-only — user signs in with Google, lookup by email in `users` table; no password rot. |
| LLM (answers) | **Claude Sonnet 4.6** | Best Hebrew Q&A reasoning in benchmarks we ran; tool-use forces structured output. |
| LLM (extraction/classification) | **Claude Haiku 4.5** | ~10× cheaper, plenty smart for filename→title and lexicon-suggestion tasks. |
| Embeddings | **Cohere `embed-multilingual-v3.0` (1024-dim)** | Better Hebrew than OpenAI 3-large in our benchmark; per-call pricing is friendly. |
| Embeddings (fallback) | **OpenAI `text-embedding-3-large`** | Wired in as a hot alternative — flip `EMBEDDING_PROVIDER=openai` to swap. Vendor redundancy on the highest-volume external call. |
| Reranker | **Cohere Rerank** | Tightens retrieval; multilingual, including Hebrew. |
| OCR | **Azure Document Intelligence** (`prebuilt-read`, Qatar Central region) | Best Hebrew scanned-PDF OCR; logical-order output (no BiDi reversal — *usually*). |
| Email | **Resend Pro** (planned) | Magic-link / notification email; custom `@elrom.tv` sending domain. |
| Domain | **elrom.tv** (already owned) | |

---

## 5. Components & roles

### Backend

```
app/
├── main.py              # FastAPI entry; middleware (CORS, sessions); router wiring
├── config.py            # Settings (env-var loaded)
├── db.py                # SQLAlchemy engine + session
├── models.py            # All ORM models (Tenant, User, Document, Chunk, Query,
│                         AuthoritativeAnswer, GoldenQuestion, Lexicon)
├── routes/
│   ├── auth.py          # Google OAuth verify + session cookie
│   ├── health.py        # /api/health + bootstrap-tenant admin endpoint
│   ├── ingest.py        # File upload → extract → chunk → embed → store
│   ├── documents.py     # List, delete, classify (Haiku-driven titles), inspect chunks, fix RTL
│   ├── search.py        # The query pipeline (cache → retrieve → answer)
│   ├── reviewer.py      # Queue, approve/edit/reject, authoritative library, lexicon CRUD + suggestions
│   └── eval.py          # Golden questions CRUD, run-eval, scoring
└── services/
    ├── embedding.py     # Cohere wrapper
    ├── extraction.py    # PDF/DOCX/TXT text extraction with OCR fallback
    ├── ocr.py           # Azure DI client; auto-splits PDFs by page count
    ├── retrieval.py     # Hybrid (vector + BM25) + RRF + per-doc diversity + Cohere rerank
    ├── reranker.py      # Cohere Rerank wrapper
    ├── hitl.py          # Authoritative cache lookup + near-miss surfacing
    ├── lexicon.py       # Term matching + Haiku-driven suggestion from failed queries
    └── llm.py           # Claude tool-use call; SYSTEM_PROMPT lives here
```

### Frontend

```
src/
├── main.tsx             # ReactDOM + AuthProvider
├── App.tsx              # Auth gate; brand nav; tab routing
├── lib/
│   ├── api.ts           # Typed fetch wrapper; credentials: include
│   └── auth.tsx         # AuthProvider context; useAuth hook
└── pages/
    ├── Login.tsx        # Google Identity Services button
    ├── Search.tsx       # The main Q&A view; debug panel; near-miss surfacing
    ├── Upload.tsx       # Drag-and-drop + queue + classify-all button
    ├── Review.tsx       # Reviewer queue; retry button per query
    ├── Authoritative.tsx# Manage the HITL cache
    ├── Lexicon.tsx      # Term CRUD + suggestion accept/reject
    └── Eval.tsx         # Golden questions + run-eval dashboard
```

### Hard rules (the ones we will not break)

- **The LLM never answers without a retrieved chunk.** No "general knowledge" fallback.
- **References are structured, not inline-marker.** Every cited section returns as `{title, section_number, source_type, excerpt}`.
- **Authoritative cache bypasses the LLM entirely.** Reviewer-approved answers are served verbatim.
- **No cross-tenant data leakage.** *(Currently enforced by "first tenant wins" — see v0.3 roadmap.)*

---

## 6. Pricing

See [`BILLING.md`](./BILLING.md) for the per-service breakdown. Forward-looking unit economics:

### At 1,000 queries / month (one design-partner pilot)

| Cost | Estimate |
|---|---|
| Render Starter ($21/mo) | $21 |
| Anthropic (Sonnet @ avg 4K in / 600 out per query) | ~$20 |
| Cohere (embed + rerank) | ~$2 |
| Azure DI (one-time ingest cost, then trivial) | < $1/mo at steady state |
| Resend Pro | $20 |
| **Total** | **~$65 / month** |

### At 10,000 queries / month

| Cost | Estimate |
|---|---|
| Render (likely needs upgrade to Standard or Pro) | ~$50 |
| Anthropic (with HITL cache hit rate growing toward 30%) | ~$140 |
| Cohere | ~$15 |
| Azure DI | < $5/mo |
| Resend Pro | $20 |
| **Total** | **~$230 / month** |

At a pilot price of $200–500/month per design-partner kibbutz, unit economics work from query 1.

---

## 7. Current state (v0.1 — shipped)

What's actually running in production today:

- ✅ Google OAuth login (invite-only via email in `users` table)
- ✅ Multi-format upload (PDF text-extract, PDF→OCR fallback, DOCX, TXT)
- ✅ Per-document AI classification (title, doc_type, summary)
- ✅ Per-document **chunk inspection** + **RTL-reversed text repair** endpoints
- ✅ Hybrid retrieval (vector + BM25 + RRF + Cohere rerank)
- ✅ **Per-document diversity cap** at both candidate and final stages
- ✅ HITL authoritative-answer cache + near-miss surfacing
- ✅ Tenant lexicon (manual CRUD + Haiku-driven suggestions from failed queries)
- ✅ Claude Sonnet answer generation with **tool-use schema** (no JSON parsing bugs)
- ✅ Domain-specific Hebrew system prompt (hierarchy, member-status distinction, intent classification, brevity, no headers)
- ✅ **Retrieval debug panel** (per-stage scores)
- ✅ **Failure-mode tagging** (retrieval miss vs wrong generation)
- ✅ **Golden Q&A eval harness** with per-question scoring
- ✅ **Retry** button in reviewer queue (re-run a question against the current pipeline)
- ✅ Auto-OCR splitting for multi-page PDFs (workaround for Azure DI silent truncation)

22 documents indexed for קיבוץ אל-רום. Real users (Tal, Noam) using daily.

Tenant scoping is currently "first tenant wins" — fine while there's exactly one tenant, breaks on the second. See v0.3.

---

## 8. Roadmap (by release)

### v0.2 — *Measurement & Retrieval Quality*

The point of this release: **stop flying blind**, then push retrieval recall hard. Every change should land alongside an eval delta.

- **Build the golden set (20+ questions)** with `expected_doc_filenames` and `expected_keywords`. Establish baseline scores.
- **Section-aware chunking.** Today: char-window splits. Replace with a splitter that respects bylaw section boundaries (`1.1.1`, `10.2`, etc.) — preserves the natural semantic unit and dramatically improves "is this chunk the right answer" rerank scores.
- **Hebrew-aware BM25.** Postgres FTS `simple` dictionary doesn't lemmatize Hebrew, so `ירש` and `ירושה` don't match. Add a Hebrew analyzer (precompute stems at ingest time as a separate column).
- **Lexicon-driven query rewriting.** When a known lexicon term matches the user's question, expand it *into the embedding query*, not just the LLM prompt. Today the term is explained to the LLM but the retrieval still searches the unexpanded form.
- **HyDE** (hypothetical-doc embeddings). Add as an optional retrieval mode, A/B against the baseline on the golden set; ship if it wins.
- **Multi-query fan-out.** Haiku generates 3 rephrasings, retrieve for each, RRF-fuse. Same A/B treatment.
- **Re-OCR pass** on any document where chunk count looks suspiciously low vs page count.

### v0.3 — *Multi-tenant Production Readiness*

The point: stop being a single-customer demo, start being a platform.

- **Real tenant scoping.** Every DB query that today picks "the first tenant" gets `tenant_id=current_user.tenant_id` wired in. Audit + test.
- **Tenant onboarding flow.** Sign up → name your organization → seed lexicon (templates by segment: kibbutz shitufi, kibbutz mitchadesh, moshav) → upload docs → done. End state: a new tenant can self-serve to first answer within an hour.
- **Per-tenant cost dashboard.** Show admin: queries this month, LLM cost, cache hit rate, top failed queries.
- **Magic-link login alongside Google.** Resend Pro integration (the env var slot exists, the flow doesn't yet).
- **Tenant data export.** GDPR/PII hygiene; "download all my data" + "delete my tenant" endpoints.

### v0.4 — *HITL Workflow & Authoritative Library*

The point: the reviewer is the bottleneck. Reduce their per-answer cost.

- **Bulk approve/reject in the reviewer queue** (keyboard shortcuts: `A` approve, `R` reject, `E` edit, `J/K` navigate).
- **Diff view** for edited answers — show LLM original vs reviewer-edited, side by side, with `git`-style highlighting.
- **Authoritative-answer versioning + retire/replace** — when a bylaw changes, retire affected authoritative answers and prompt the reviewer to re-author.
- **Auto-suggest authoritative answer** when reviewer opens a query — search for similar already-approved answers and offer "promote based on this template."
- **Reviewer analytics** — which docs/questions are the highest-volume failure source; weekly "you have N untouched negative-feedback queries" digest.

### v0.5 — *Generation Quality & Answer Tuning*

The point: with retrieval solid and HITL fast, push answer prose toward "reads like a great human secretary."

- **Eval-driven prompt iteration loop** (formalized: every prompt change must improve composite score on the golden set, or revert).
- **Answer-length awareness.** Today the prompt says "short." Add explicit type-routing: yes/no → 1 sentence, "what is X?" → 2 paragraphs, "what's the process?" → numbered list.
- **Self-consistency for high-stakes questions.** When `confidence=uncertain` and the topic touches money/property, run the LLM twice with different chunk orderings and only return the consensus.
- **Inline-citation hover tooltips on the frontend** — hover a section number, see the excerpt without scrolling.

### v1.0 — *UI polish, accessibility, and "share-ability"*

Cosmetic but worth doing well before pitching beyond design partners.

- **Mobile responsive layout** (today the nav is desktop-only).
- **Israeli accessibility compliance** — IS 5568 + WCAG 2.1 AA for Hebrew RTL (mandatory under the Equal Rights for Persons with Disabilities Act in Israel; non-compliance carries fines).
- **Search history** (per-user) and **bookmarked answers**.
- **Shareable answer links** (`/answer/<query_id>` — copy-link, read-only).
- **Document thumbnails** on the מסמכים tab.
- **Light/dark theme.**
- **Empty-state illustrations** and richer loading skeletons.
- **Notification system** ("your bylaw question got an authoritative answer — view it").

### Backlog (post-v1.0, ordered by interest, not priority)

- Slack / WhatsApp bot integrations
- Mobile native (React Native — the React frontend is already typescript)
- Question-difficulty estimation (route hard questions to better/longer-context model)
- Cross-tenant anonymized analytics ("90% of kibbutzim asked about X this quarter")
- Fine-tuned Hebrew embedding model
- Read-only public knowledge pages (per-tenant, opt-in)
- Live "ask a question" widget for the kibbutz's own website

---

*Doc owner: Tal Gurevich. Last updated: v0.1 ship date.*
