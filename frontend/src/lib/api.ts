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

export type SearchResponse = {
  query_id: string;
  question: string;
  answer: string;
  confidence: "confident" | "uncertain" | "refused";
  sources: Source[];
  llm_used: boolean;
  served_from: "hitl_cache" | "llm" | "no_documents";
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
};

export type CurrentUser = {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
  tenant_id: string;
};

export type UploadResponse = {
  document_id: string;
  chunks_created: number;
  used_ocr: boolean;
  extractor: string | null;
  note: string | null;
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

  search: (question: string) =>
    request<SearchResponse>("/api/search", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  feedback: (queryId: string, feedback: "positive" | "negative") =>
    request<{ status: string }>(`/api/search/${queryId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ feedback }),
    }),

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
