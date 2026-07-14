const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Identity service — every auth-related call (login, register, /me,
// logout, tenant-switch, password reset) goes here instead of the
// Takanon backend now that identity was extracted. Cookies are shared
// across .klaser.co.il in production so both bases see the same session.
const IDENTITY_BASE =
  import.meta.env.VITE_IDENTITY_BASE_URL || "http://localhost:8001";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Best-effort extraction of a human-readable message from any thrown
 * error — unwraps FastAPI's {"detail": "..."} body when present. */
export function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const parsed = JSON.parse(err.message);
      if (parsed?.detail) return parsed.detail;
    } catch {
      // not JSON — fall through to the raw message
    }
    return err.message.replace(/^\{"detail":"|"\}$/g, "");
  }
  return err instanceof Error ? err.message : String(err);
}

async function _fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return _fetchJson<T>(`${BASE}${path}`, init);
}

/** Same shape as `request` but hits the identity service instead of the
 * Takanon backend. Used for all auth endpoints. */
async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  return _fetchJson<T>(`${IDENTITY_BASE}${path}`, init);
}

// ─── Types ─────────────────────────────────────────────────────────────
export type Source = {
  chunk_id: string;
  document_id?: string | null;
  document_filename: string;
  section_path: string | null;
  text: string;
  has_file?: boolean;
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

export type TurnMode = "answer" | "clarify";

export type SearchResponse = {
  query_id: string;
  conversation_id: string;
  turn_index: number;
  // Chat triage outcome. "answer" = sources + answer in this response.
  // "clarify" = the assistant asked for clarification; no sources yet.
  mode: TurnMode;
  // Rewritten query actually used for retrieval, when it differs from
  // `question`. Surfaced for debugging / golden-set diagnosis.
  canonical_query: string | null;
  clarifying_message: string | null;
  candidate_docs: string[];
  question: string;
  answer: string;
  // "clarifying" appears alongside the legacy confidence values when
  // mode == "clarify".
  confidence: "confident" | "uncertain" | "refused" | "clarifying";
  sources: Source[];
  references: StructuredReference[];
  llm_used: boolean;
  served_from: "hitl_cache" | "llm" | "no_documents" | "clarify";
  retrieval_debug: RetrievalDebug | null;
  near_misses: NearMiss[];
};

export type ConversationSummary = {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  turn_count: number;
  last_user_question: string | null;
  last_assistant_answer: string | null;
};

export type TurnSource = {
  chunk_id: string;
  document_filename: string;
  section_path: string | null;
};

export type ConversationTurn = {
  query_id: string;
  turn_index: number | null;
  question: string;
  answer: string | null;
  confidence: string | null;
  mode: TurnMode;
  sources: TurnSource[];
  feedback: string | null;
  created_at: string;
};

export type ConversationDetail = {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  turns: ConversationTurn[];
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
  conversation_id: string | null;
  turn_index: number | null;
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
  source: "manual" | "learned";
  status: "active" | "pending" | "rejected";
  confidence: number | null;
  evidence: Record<string, unknown> | null;
  updated_at: string;
};

export type AmendmentItem = {
  id: string;
  amendment_doc_id: string;
  amendment_doc_filename: string;
  target_doc_id: string;
  target_doc_filename: string;
  target_section: string;
  action: "replace" | "add_after" | "add_before" | "delete" | "clarify";
  old_text: string | null;
  new_text: string | null;
  effective_date: string | null;
  rationale: string | null;
  evidence_span: string | null;
  extractor_confidence: number | null;
  needs_review: boolean;
  created_at: string;
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
  // AI-extracted / user-editable metadata surfaced in the review dialog.
  effective_date?: string | null;
  document_date?: string | null;
  meeting_number?: string | null;
  decision_number?: string | null;
  bylaw_section_range?: string | null;
  parties?: string[] | null;
  metadata_reviewed?: boolean;
  // True when the original file is stored on disk and can be opened in-browser.
  has_file?: boolean;
};

/** Absolute URL to stream the original uploaded file. Opens in the browser's
 *  built-in PDF viewer via Content-Disposition: inline. */
export function documentFileUrl(documentId: string): string {
  return `${BASE}/api/documents/${documentId}/file`;
}

export type ChunkPreview = {
  position: number;
  section_path: string | null;
  chars: number;
  text: string;
};

export type DocumentMetadataPatch = Partial<{
  doc_type: string;
  folder: string;
  effective_date: string;
  document_date: string;
  meeting_number: string;
  decision_number: string;
  bylaw_section_range: string;
  parties: string[];
  summary: string;
}>;

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

export type RegistrationInfo = {
  email: string;
  display_name: string | null;
  tenant_name: string;
  role: string;
};

export type ResetPasswordInfo = {
  email: string;
};

// Admin panel — super-admin only
export type TenantSegment = "kibbutz_shitufi" | "kibbutz_mitchadesh" | "moshav";

export type AdminTenant = {
  id: string;
  name: string;
  segment: string;
  user_count: number;
  document_count: number;
  created_at: string;
};

export type AdminUser = {
  id: string;
  email: string;
  display_name: string | null;
  role: "admin" | "reviewer" | "secretary";
  is_super_admin: boolean;
  tenant_id: string;
  tenant_name: string | null;
  created_at: string;
  has_password: boolean;
};

export type CreateTenantPayload = {
  name: string;
  segment: TenantSegment;
};

export type CreateUserPayload = {
  tenant_id: string;
  email: string;
  role: AdminUser["role"];
  display_name?: string | null;
  is_super_admin?: boolean;
};

export type UpdateUserPayload = Partial<{
  role: AdminUser["role"];
  display_name: string | null;
  is_super_admin: boolean;
  tenant_id: string;
}>;

export type TenantContext = {
  id: string;
  name: string;
  segment: string;
  system_context: string | null;
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
  // Public contact form (unauthenticated)
  sendContact: (body: { name: string; email: string; phone?: string; message: string }) =>
    request<{ status: string }>("/api/contact", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Auth — every call below goes to the identity service (auth.klaser.co.il)
  // via authRequest, not to the Takanon backend. Cookies span .klaser.co.il
  // so both bases see the same session.
  me: () => authRequest<CurrentUser>("/api/auth/me"),
  googleLogin: (credential: string) =>
    authRequest<CurrentUser>("/api/auth/google", {
      method: "POST",
      body: JSON.stringify({ credential }),
    }),
  logout: () =>
    authRequest<{ status: string }>("/api/auth/logout", { method: "POST" }),
  passwordLogin: (email: string, password: string) =>
    authRequest<CurrentUser>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  getRegistrationInfo: (token: string) =>
    authRequest<RegistrationInfo>(
      `/api/auth/registration/${encodeURIComponent(token)}`,
    ),
  register: (token: string, password: string, displayName?: string) =>
    authRequest<CurrentUser>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ token, password, display_name: displayName || null }),
    }),

  forgotPassword: (email: string) =>
    authRequest<{ status: string }>("/api/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  getResetPasswordInfo: (token: string) =>
    authRequest<ResetPasswordInfo>(
      `/api/auth/reset-password/${encodeURIComponent(token)}`,
    ),
  resetPassword: (token: string, password: string) =>
    authRequest<CurrentUser>("/api/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),

  // Super-admin only — driving the tenant switcher (also on identity now)
  listTenants: () => authRequest<TenantItem[]>("/api/auth/tenants"),
  switchTenant: (tenantId: string) =>
    authRequest<CurrentUser>("/api/auth/switch-tenant", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId }),
    }),
  exitSwitch: () =>
    authRequest<CurrentUser>("/api/auth/exit-switch", { method: "POST" }),

  search: (question: string, conversationId?: string | null) =>
    request<SearchResponse>("/api/search", {
      method: "POST",
      body: JSON.stringify({ question, conversation_id: conversationId || null }),
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
    onEvent: (ev: SearchStreamEvent) => void,
    conversationId?: string | null
  ): Promise<SearchResponse> => {
    const r = await fetch(`${BASE}/api/search/stream`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, conversation_id: conversationId || null }),
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

  markGood: (queryId: string) =>
    request<{ status: string; authoritative_answer_id: string | null }>(
      `/api/search/${queryId}/mark-good`,
      { method: "POST" }
    ),
  markBroken: (queryId: string) =>
    request<{ status: string; cached_answer_retired?: boolean }>(
      `/api/search/${queryId}/mark-broken`,
      { method: "POST" }
    ),

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
  getDocumentChunks: (id: string) =>
    request<ChunkPreview[]>(`/api/documents/${id}/chunks`),
  updateDocumentMetadata: (id: string, patch: DocumentMetadataPatch) =>
    request<{ status: string }>(`/api/documents/${id}/metadata`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
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

  // Conversations
  listConversations: (limit = 30) =>
    request<ConversationSummary[]>(`/api/conversations?limit=${limit}`),
  getConversation: (id: string) =>
    request<ConversationDetail>(`/api/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    request<{ status: string }>(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: string) =>
    request<{ status: string }>(`/api/conversations/${id}`, { method: "DELETE" }),

  // Lexicon
  listLexicon: () => request<LexiconItem[]>("/api/reviewer/lexicon"),
  suggestLexicon: () =>
    request<LexiconSuggestion[]>("/api/reviewer/lexicon/suggestions", { method: "POST" }),
  createLexicon: (body: { term: string; expansion: string; notes?: string }) =>
    request<LexiconItem>("/api/reviewer/lexicon", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateLexicon: (
    id: string,
    body: Partial<{ term: string; expansion: string; notes: string; status: "active" | "pending" | "rejected" }>
  ) =>
    request<{ status: string }>(`/api/reviewer/lexicon/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteLexicon: (id: string) =>
    request<{ status: string }>(`/api/reviewer/lexicon/${id}`, { method: "DELETE" }),

  // Amendments — cross-document supersession graph
  listAmendments: (needsReview?: boolean) => {
    const qs = needsReview === undefined ? "" : `?needs_review=${needsReview}`;
    return request<AmendmentItem[]>(`/api/reviewer/amendments${qs}`);
  },
  updateAmendment: (
    id: string,
    body: Partial<{
      target_section: string;
      action: AmendmentItem["action"];
      new_text: string;
      effective_date: string;
      rationale: string;
    }>,
  ) =>
    request<{ status: string }>(`/api/reviewer/amendments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  approveAmendment: (id: string) =>
    request<{ status: string; chunks_superseded: number }>(
      `/api/reviewer/amendments/${id}/approve`,
      { method: "POST" },
    ),
  rejectAmendment: (id: string) =>
    request<{ status: string }>(`/api/reviewer/amendments/${id}/reject`, {
      method: "POST",
    }),

  // Super-admin management panel
  adminListTenants: () => request<AdminTenant[]>("/api/admin/tenants"),
  adminCreateTenant: (body: CreateTenantPayload) =>
    request<AdminTenant>("/api/admin/tenants", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminListUsers: (tenantId?: string) => {
    const qs = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
    return request<AdminUser[]>(`/api/admin/users${qs}`);
  },
  adminCreateUser: (body: CreateUserPayload) =>
    request<AdminUser>("/api/admin/users", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminUpdateUser: (userId: string, body: UpdateUserPayload) =>
    request<AdminUser>(`/api/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  adminDeleteUser: (userId: string) =>
    request<{ status: string }>(`/api/admin/users/${userId}`, {
      method: "DELETE",
    }),
  adminResendInvite: (userId: string) =>
    request<{ status: string }>(`/api/admin/users/${userId}/resend-invite`, {
      method: "POST",
    }),

  adminDebugQueue: (tenantId?: string) => {
    const qs = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
    return request<DebugQueueItem[]>(`/api/admin/debug-queue${qs}`);
  },
  adminDismissDebug: (queryId: string) =>
    request<{ status: string }>(
      `/api/admin/debug-queue/${queryId}/dismiss`,
      { method: "POST" }
    ),

  adminGetTenant: (tenantId: string) =>
    request<TenantContext>(`/api/admin/tenants/${tenantId}`),
  adminUpdateTenantContext: (tenantId: string, systemContext: string | null) =>
    request<TenantContext>(
      `/api/admin/tenants/${tenantId}/system-context`,
      {
        method: "PATCH",
        body: JSON.stringify({ system_context: systemContext }),
      }
    ),
};

export type DebugChunk = {
  chunk_id: string;
  document_id: string;
  document_filename: string;
  section_path: string | null;
  text: string;
};

export type DebugQueueItem = {
  query_id: string;
  tenant_id: string;
  tenant_name: string | null;
  question: string;
  answer: string | null;
  confidence: string | null;
  llm_used: boolean;
  created_at: string;
  retrieval_debug: RetrievalDebug | null;
  source_chunks: DebugChunk[];
};
