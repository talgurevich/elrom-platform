const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new ApiError(r.status, body || r.statusText);
  }
  return r.json();
}

// ─── Types ─────────────────────────────────────────────────────────────
export type Source = {
  chunk_id: string;
  document_filename: string;
  section_path: string | null;
  text: string;
};

export type RetrievalDebugRow = {
  chunk_id: string;
  document_filename: string;
  section_path: string | null;
  cosine_similarity?: number;
  ts_rank?: number;
  fusion_score?: number;
  rank?: number;
};

export type RetrievalDebug = {
  vector: RetrievalDebugRow[];
  bm25: RetrievalDebugRow[];
  fused: RetrievalDebugRow[];
  reranked: RetrievalDebugRow[];
};

export type StructuredReference = {
  title: string;
  section_number: string;
  source_type: string;
  excerpt: string;
};

export type NearMiss = {
  authoritative_answer_id: string;
  canonical_question: string;
  answer: string;
  similarity: number;
};

export type SearchResponse = {
  query_id: string;
  question: string;
  answer: string;
  confidence: "confident" | "uncertain" | "refused";
  sources: Source[];
  references: StructuredReference[];
  llm_used: boolean;
  served_from: "hitl_cache" | "llm" | "no_documents";
  retrieval_debug: RetrievalDebug | null;
  near_misses: NearMiss[];
};

export type SearchPipelineStage =
  | "analyzing"
  | "searching"
  | "ranking"
  | "generating";

export type SearchStreamEvent =
  | { type: "stage"; stage: SearchPipelineStage }
  | { type: "detail"; text: string }
  | { type: "done"; response: SearchResponse }
  | { type: "error"; detail: string };

export type LexiconSuggestion = {
  term: string;
  expansion: string;
  why: string;
  source_question: string;
  source_query_id: string;
};

export type FailureMode = "retrieval_miss" | "wrong_generation" | "other";

export type Golden = {
  id: string;
  question: string;
  expected_doc_filenames: string[] | null;
  expected_keywords: string[] | null;
  expected_answer: string | null;
  notes: string | null;
  source_query_id: string | null;
  created_at: string;
  last_run_at: string | null;
  last_score: number | null;
  last_retrieval_score: number | null;
  last_keyword_score: number | null;
  last_confidence: string | null;
};

export type GoldenInput = {
  question: string;
  expected_doc_filenames?: string[];
  expected_keywords?: string[];
  expected_answer?: string;
  notes?: string;
};

export type EvalRunResult = {
  golden_id: string;
  question: string;
  score: number;
  retrieval_score: number | null;
  keyword_score: number | null;
  confidence: string;
  retrieved_filenames: string[];
  missing_filenames: string[];
  missing_keywords: string[];
};

export type EvalSummary = {
  total: number;
  avg_score: number;
  avg_retrieval: number | null;
  avg_keyword: number | null;
  confidence_counts: Record<string, number>;
  results: EvalRunResult[];
};

export type QueryListItem = {
  id: string;
  question: string;
  answer: string | null;
  confidence: string | null;
  llm_used: boolean;
  feedback: string | null;
  reviewer_action: string | null;
  served_from_cache: boolean;
  created_at: string;
};

export type AuthoritativeItem = {
  id: string;
  canonical_question: string;
  answer: string;
  status: "active" | "retired";
  similarity_threshold: number;
  internal_note: string | null;
  approved_at: string;
};

export type LexiconItem = {
  id: string;
  term: string;
  expansion: string;
  notes: string | null;
  updated_at: string;
};

export type DocumentItem = {
  id: string;
  filename: string;
  doc_type: string | null;
  chunks: number;
  chars: number;
  ingested_at: string;
  summary?: string | null;
  ai_classified?: boolean;
  folder?: string | null; // AI-assigned topical folder
  // Extraction telemetry
  extractor?: string | null;
  used_ocr?: boolean;
  pages?: number | null;
  chars_extracted?: number | null;
  extraction_partial?: boolean;
  extraction_note?: string | null;
  quality?: "ok" | "partial" | "low_density" | "suspect" | "unknown";
};

export type ClassifyResult = {
  document_id: string;
  old_filename: string;
  new_filename: string;
  doc_type: string | null;
  summary: string | null;
  skipped: boolean;
  reason?: string;
};

export type ClassifySummary = {
  total: number;
  classified: number;
  skipped: number;
  results: ClassifyResult[];
};

export type CurrentUser = {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
  tenant_id: string;
  tenant_name: string | null;
  is_super_admin?: boolean;
  home_tenant_id?: string | null;
  home_tenant_name?: string | null;
  viewing_other_tenant?: boolean;
};

export type TenantItem = {
  id: string;
  name: string;
  segment: string;
};

export type UploadResponse = {
  document_id: string;
  chunks_created: number;
  used_ocr: boolean;
  extractor: string | null;
  note: string | null;
  pages?: number | null;
  chars_extracted?: number | null;
  partial?: boolean;
};

// ─── Endpoints ─────────────────────────────────────────────────────────
export const api = {
  // Auth
  me: () => request<CurrentUser>("/api/auth/me"),
  googleLogin: (credential: string) =>
    request<CurrentUser>("/api/auth/google", {
      method: "POST",
      body: JSON.stringify({ credential }),
    }),
  logout: () => request<{ status: string }>("/api/auth/logout", { method: "POST" }),

  // Super-admin only — driving the tenant switcher
  listTenants: () => request<TenantItem[]>("/api/auth/tenants"),
  switchTenant: (tenantId: string) =>
    request<CurrentUser>("/api/auth/switch-tenant", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId }),
    }),
  exitSwitch: () =>
    request<CurrentUser>("/api/auth/exit-switch", { method: "POST" }),

  search: (question: string) =>
    request<SearchResponse>("/api/search", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  recentQuestions: (limit = 8) =>
    request<string[]>(`/api/search/recent?limit=${limit}`),

  /**
   * Streaming search via Server-Sent Events. Calls `onEvent` for every
   * progress event as the pipeline runs. Resolves with the final
   * SearchResponse from the "done" event.
   *
   * EventSource doesn't support POST, so we use fetch + ReadableStream.
   */
  searchStream: async (
    question: string,
    onEvent: (ev: SearchStreamEvent) => void
  ): Promise<SearchResponse> => {
    const r = await fetch(`${BASE}/api/search/stream`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question }),
    });
    if (!r.ok || !r.body) {
      const body = await r.text().catch(() => "");
      throw new ApiError(r.status, body || r.statusText);
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let finalResponse: SearchResponse | null = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by a blank line. Each event has one or more
      // "data: ..." lines whose payloads (here) are JSON objects.
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const dataLines = rawEvent
          .split("\n")
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trimStart());
        if (!dataLines.length) continue;
        const payloadStr = dataLines.join("\n");
        let payload: SearchStreamEvent;
        try {
          payload = JSON.parse(payloadStr);
        } catch {
          continue;
        }
        onEvent(payload);
        if (payload.type === "done") {
          finalResponse = payload.response;
        } else if (payload.type === "error") {
          throw new ApiError(500, payload.detail);
        }
      }
    }

    if (!finalResponse) {
      throw new ApiError(500, "Stream ended without a result");
    }
    return finalResponse;
  },

  feedback: (queryId: string, feedback: "positive" | "negative") =>
    request<{ status: string; cached_answer_retired?: boolean }>(
      `/api/search/${queryId}/feedback`,
      { method: "POST", body: JSON.stringify({ feedback }) }
    ),

  tagFailureMode: (queryId: string, failureMode: FailureMode) =>
    request<{ status: string }>(`/api/search/${queryId}/failure-mode`, {
      method: "POST",
      body: JSON.stringify({ failure_mode: failureMode }),
    }),

  // Eval / goldens
  listGoldens: () => request<Golden[]>("/api/eval/goldens"),
  createGolden: (body: GoldenInput) =>
    request<Golden>("/api/eval/goldens", { method: "POST", body: JSON.stringify(body) }),
  promoteQueryToGolden: (queryId: string, body?: Partial<GoldenInput>) =>
    request<Golden>(`/api/eval/goldens/from-query/${queryId}`, {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
  deleteGolden: (id: string) =>
    request<{ status: string }>(`/api/eval/goldens/${id}`, { method: "DELETE" }),
  runEval: () => request<EvalSummary>("/api/eval/run", { method: "POST" }),

  // Reviewer queue
  listQueries: (params?: { needs_review?: boolean; feedback_only?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.needs_review) qs.set("needs_review", "true");
    if (params?.feedback_only) qs.set("feedback_only", "true");
    qs.set("limit", "100");
    return request<QueryListItem[]>(`/api/reviewer/queries?${qs.toString()}`);
  },
  approve: (queryId: string, body?: { edited_answer?: string; internal_note?: string; similarity_threshold?: number }) =>
    request<{ authoritative_answer_id: string; canonical_question: string; answer: string }>(
      `/api/reviewer/queries/${queryId}/approve`,
      { method: "POST", body: JSON.stringify(body || {}) }
    ),
  reject: (queryId: string) =>
    request<{ status: string }>(`/api/reviewer/queries/${queryId}/reject`, { method: "POST" }),

  // Authoritative library
  listAuthoritative: () => request<AuthoritativeItem[]>("/api/reviewer/authoritative"),
  updateAuthoritative: (id: string, body: Partial<{ answer: string; similarity_threshold: number; internal_note: string; status: "active" | "retired" }>) =>
    request<{ status: string }>(`/api/reviewer/authoritative/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  // Documents
  listDocuments: () => request<DocumentItem[]>("/api/documents"),
  deleteDocument: (id: string) =>
    request<{ status: string }>(`/api/documents/${id}`, { method: "DELETE" }),
  deleteAllDocuments: () =>
    request<{ status: string; documents_deleted: number; chunks_deleted: number }>(
      `/api/documents?confirm=true`,
      { method: "DELETE" }
    ),
  classifyDocuments: (force = false) =>
    request<ClassifySummary>(
      `/api/documents/classify${force ? "?force=true" : ""}`,
      { method: "POST" }
    ),
  uploadDocument: async (file: File, docType?: string): Promise<UploadResponse> => {
    const fd = new FormData();
    fd.append("file", file);
    if (docType) fd.append("doc_type", docType);
    const r = await fetch(`${BASE}/api/ingest/upload`, {
      method: "POST",
      body: fd,
      credentials: "include",
    });
    if (!r.ok) throw new ApiError(r.status, (await r.text()) || r.statusText);
    return r.json();
  },

  // Lexicon
  listLexicon: () => request<LexiconItem[]>("/api/reviewer/lexicon"),
  suggestLexicon: () =>
    request<LexiconSuggestion[]>("/api/reviewer/lexicon/suggestions", { method: "POST" }),
  createLexicon: (body: { term: string; expansion: string; notes?: string }) =>
    request<LexiconItem>("/api/reviewer/lexicon", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateLexicon: (id: string, body: Partial<{ term: string; expansion: string; notes: string }>) =>
    request<{ status: string }>(`/api/reviewer/lexicon/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteLexicon: (id: string) =>
    request<{ status: string }>(`/api/reviewer/lexicon/${id}`, { method: "DELETE" }),
};
