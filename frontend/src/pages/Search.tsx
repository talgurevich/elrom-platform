import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  api,
  documentFileUrl,
  type AnswerAnnotation,
  type ConversationSummary,
  type FailureMode,
  type RetrievalDebug,
  type RetrievalDebugRow,
  type SearchPipelineStage,
  type SearchResponse,
  type StructuredReference,
  type Source,
} from "../lib/api";

// A single turn in the chat thread. Mirrors the relevant fields of
// SearchResponse plus mutable per-turn UI state (feedback, golden-promote).
type ChatTurn = {
  query_id: string;
  conversation_id: string;
  turn_index: number;
  mode: "answer" | "clarify";
  question: string;
  answer: string;
  confidence: string;
  sources: Source[];
  references: StructuredReference[];
  unverified_reference_count: number;
  retrieval_debug: RetrievalDebug | null;
  candidate_docs: string[];
  clarifying_message: string | null;
  served_from: string;
  answer_annotations: AnswerAnnotation[];
  // Per-turn mutable UI state
  feedback: "positive" | "negative" | null;
  failure_mode: FailureMode | null;
  promoted: boolean;
  promoting: boolean;
  retrying: boolean;
  just_retried: boolean;
};

const confidenceLabel: Record<string, string> = {
  confident: "תשובה מבוססת",
  uncertain: "תשובה חלקית",
  refused: "אין תשובה במאגר",
  clarifying: "מבקש הבהרה",
};

function responseToTurn(r: SearchResponse): ChatTurn {
  return {
    query_id: r.query_id,
    conversation_id: r.conversation_id,
    turn_index: r.turn_index,
    mode: r.mode,
    question: r.question,
    answer: r.answer,
    confidence: r.confidence,
    sources: r.sources,
    references: r.references || [],
    unverified_reference_count: r.unverified_reference_count ?? 0,
    retrieval_debug: r.retrieval_debug,
    candidate_docs: r.candidate_docs || [],
    clarifying_message: r.clarifying_message,
    served_from: r.served_from,
    answer_annotations: r.answer_annotations || [],
    feedback: null,
    failure_mode: null,
    promoted: false,
    promoting: false,
    retrying: false,
    just_retried: false,
  };
}

export default function Search() {
  // Chat thread state.
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<SearchPipelineStage | null>(null);
  const [stageDetail, setStageDetail] = useState<string | null>(null);
  // Drives the submit button's fill: solid teal while the composer has focus,
  // faded when it doesn't.
  const [composerFocused, setComposerFocused] = useState(false);
  const threadEndRef = useRef<HTMLDivElement>(null);
  // When the user opened this page from the Eval panel with ?golden=&q=,
  // we tag the *first* auto-run with that golden_id so 👍/👎 rolls into the
  // per-golden pass-rate report. Follow-up free-form turns don't inherit it.
  const pendingGoldenIdRef = useRef<string | null>(null);

  // Hydrate from ?c=<id> in the URL on mount, so refreshes preserve the thread.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const c = params.get("c");
    if (!c) return;
    let cancelled = false;
    api
      .getConversation(c)
      .then((conv) => {
        if (cancelled) return;
        setConversationId(conv.id);
        const hydrated: ChatTurn[] = conv.turns.map((t) => ({
          query_id: t.query_id,
          conversation_id: conv.id,
          turn_index: t.turn_index ?? 0,
          mode: t.mode,
          question: t.question,
          answer: t.answer || "",
          confidence: t.confidence || "",
          sources: t.sources.map((s) => ({
            chunk_id: s.chunk_id,
            document_filename: s.document_filename,
            section_path: s.section_path,
            text: "",
          })),
          references: [],
          unverified_reference_count: 0,
          retrieval_debug: null,
          candidate_docs: [],
          clarifying_message: t.mode === "clarify" ? t.answer : null,
          served_from: t.mode === "clarify" ? "clarify" : "llm",
          answer_annotations: [],
          feedback: t.feedback === "positive" || t.feedback === "negative" ? t.feedback : null,
          failure_mode: null,
          promoted: false,
          promoting: false,
          retrying: false,
          just_retried: false,
        }));
        setTurns(hydrated);
      })
      .catch(() => {
        if (cancelled) return;
        // Conversation might have been deleted or not belong to this user;
        // silently start fresh.
        setConversationId(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Deep-link from Eval panel: ?golden=<id>&q=<question> — auto-run the
  // question once, tagging the resulting Query with golden_id so 👍/👎
  // aggregates into the golden-report. We strip both params from the URL
  // after firing so a refresh doesn't re-run.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const goldenId = params.get("golden");
    const q = params.get("q");
    if (!goldenId || !q) return;
    pendingGoldenIdRef.current = goldenId;
    const url = new URL(window.location.href);
    url.searchParams.delete("golden");
    url.searchParams.delete("q");
    window.history.replaceState({}, "", url.toString());
    void runSearch(q);
    // Intentionally run-once on mount. runSearch reads latest refs/state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Mirror the conversation id into the URL (replaceState — don't pollute
  // history with a separate entry per turn).
  useEffect(() => {
    const url = new URL(window.location.href);
    if (conversationId) {
      url.searchParams.set("c", conversationId);
    } else {
      url.searchParams.delete("c");
    }
    window.history.replaceState({}, "", url.toString());
  }, [conversationId]);

  // Auto-scroll to the bottom as new turns or the progress bar appear.
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, loading]);

  const runSearch = async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setStage(null);
    setStageDetail(null);
    // Question stays in the composer during loading so the user can see what
    // they asked while the ThinkingProgress bar takes over the page. Cleared
    // only on success; on error it stays so the user can edit and retry.
    // Consume the pending golden_id (if any) so it's only attached to the
    // first run after landing on ?golden=. Follow-up turns run untagged.
    const goldenId = pendingGoldenIdRef.current;
    pendingGoldenIdRef.current = null;
    try {
      const fresh = await api.searchStream(
        q,
        (ev) => {
          if (ev.type === "stage") setStage(ev.stage);
          else if (ev.type === "detail") setStageDetail(ev.text);
        },
        conversationId,
        goldenId
      );
      if (!conversationId) setConversationId(fresh.conversation_id);
      setTurns((prev) => [...prev, responseToTurn(fresh)]);
      setQuestion("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setStage(null);
      setStageDetail(null);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    void runSearch(question);
  };

  const updateTurn = (queryId: string, patch: Partial<ChatTurn>) => {
    setTurns((prev) => prev.map((t) => (t.query_id === queryId ? { ...t, ...patch } : t)));
  };

  const submitFeedback = async (turn: ChatTurn, kind: "positive" | "negative") => {
    updateTurn(turn.query_id, { feedback: kind });
    try {
      if (kind === "positive") {
        await api.markGood(turn.query_id);
        return;
      }
      // kind === "negative" — the corpus knows, the retrieval missed.
      const resp = await api.markBroken(turn.query_id);
      // If we retired a cached answer, re-run the question so the user sees
      // a fresh attempt instead of the same wrong cached response.
      if (resp.cached_answer_retired) {
        updateTurn(turn.query_id, { retrying: true });
        try {
          const fresh = await api.search(turn.question, turn.conversation_id);
          setTurns((prev) =>
            prev.map((t) =>
              t.query_id === turn.query_id
                ? { ...responseToTurn(fresh), just_retried: true }
                : t
            )
          );
        } finally {
          updateTurn(turn.query_id, { retrying: false });
        }
      }
    } catch (err) {
      updateTurn(turn.query_id, { feedback: null });
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const startNewConversation = () => {
    setConversationId(null);
    setTurns([]);
    setError(null);
    setQuestion("");
  };

  const pickClarificationOption = (turn: ChatTurn, doc: string) => {
    // Convenience: user clicks a candidate doc → preload the input with a
    // disambiguating follow-up so they don't have to type it.
    setQuestion(`הכוונה שלי לתקנון: ${doc}. ${turn.question}`);
  };

  return (
    <>
      <header className="mb-8">
        <div className="flex items-baseline justify-between gap-4 flex-wrap mb-3">
          {/* H5 — Rubik Bold 16, tracking 25% (Klaser DS) */}
          <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise">
            שיחה
          </div>
          {(turns.length > 0 || conversationId) && (
            <button
              onClick={startNewConversation}
              className="inline-flex items-center gap-2 px-4 py-1.5 rounded-md border border-turquoise text-sm font-semibold text-turquoise bg-white hover:bg-turquoise hover:text-white transition"
              title="התחל שיחה חדשה — מנקה את ההקשר"
            >
              <span>שיחה חדשה</span>
              <PlusCircle />
            </button>
          )}
        </div>
        {turns.length === 0 ? (
          <>
            {/* H1 — Rubik Bold 72/72 (Klaser DS) */}
            <h1 className="font-rubik font-bold text-5xl md:text-[72px] md:leading-[72px] text-[#191919]">
              זיכרון ארגוני
              <br />
              בשיחה.
            </h1>
            {/* Body — Heebo Regular 18 */}
            <p className="mt-5 font-sans text-lg leading-relaxed text-[#525252] max-w-xl">
              שאל שאלה בעברית. אם משהו לא ברור — המערכת תבקש הבהרה לפני שתחפש,
              ותלמד מההמשך כדי לענות טוב יותר בפעם הבאה.
            </p>
          </>
        ) : (
          <h1 className="font-display text-3xl md:text-4xl font-black text-ink leading-tight">
            {turns[0]?.question.slice(0, 80) || "שיחה"}
            {turns[0] && turns[0].question.length > 80 && "…"}
          </h1>
        )}
      </header>

      {/* The thread — alternating user / assistant turns. */}
      <div className="space-y-8 mb-8">
        {turns.map((turn) => (
          <TurnView
            key={turn.query_id}
            turn={turn}
            onFeedback={(kind) => void submitFeedback(turn, kind)}
            onPickCandidate={(doc) => pickClarificationOption(turn, doc)}
          />
        ))}
      </div>

      {loading && <ThinkingProgress stage={stage} detail={stageDetail} />}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-900 text-sm whitespace-pre-wrap">
          {error}
        </div>
      )}

      <div ref={threadEndRef} />

      {/* Composer — sticky-ish at the bottom of the page. */}
      {/* Empty state follows the Figma box: 722×180, no padding of its own,
          column flex centered vertically, 8px gap, 8px radius. The inner rows
          carry the inset instead, so nothing touches the border. Once the
          thread starts, the composer goes back to a compact padded bar. */}
      <form
        onSubmit={submit}
        className={`mt-6 sticky bottom-4 bg-surface border border-line shadow-soft rounded-[8px] flex flex-col gap-2 ${
          turns.length === 0
            ? "justify-center items-start w-full max-w-[722px] h-[180px] p-0"
            : "p-3"
        }`}
      >
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onFocus={() => setComposerFocused(true)}
          onBlur={() => setComposerFocused(false)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              void runSearch(question);
            }
          }}
          placeholder={
            turns.length === 0
              ? "לדוגמה: ירשתי בית בקיבוץ ואני לא חבר. מה עושים?"
              : "תגובה / שאלת המשך…"
          }
          rows={turns.length === 0 ? 3 : 2}
          disabled={loading}
          className="w-full px-3 py-2 bg-surface outline-none text-base resize-none placeholder:text-ink-soft/70 disabled:opacity-60"
        />
        {/* justify-end puts this group on the LEFT under RTL. The shortcut hint
            comes first in the DOM so the button ends up furthest left. */}
        <div
          className={`w-full flex items-center justify-end gap-3 flex-wrap ${
            turns.length === 0 ? "px-3" : ""
          }`}
        >
          <span className="text-xs text-ink-soft">Cmd/Ctrl + Enter</span>
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className={`px-6 py-2 rounded-md text-surface font-bold tracking-wide transition disabled:cursor-not-allowed ${
              composerFocused || question.trim()
                ? "bg-turquoise hover:bg-turquoise-dark"
                : "bg-turquoise/50"
            }`}
          >
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <span className="inline-block w-2.5 h-2.5 bg-surface animate-pulse" />
                <span>חושב</span>
              </span>
            ) : turns.length === 0 ? (
              "שאל"
            ) : (
              "שלח"
            )}
          </button>
        </div>
      </form>

      {/* Disclaimer — sits under the box, matching the ChatGPT/Claude pattern. */}
      <p className="mt-2 w-full max-w-[722px] text-center text-xs text-ink-soft">
        בינה מלאכותית עלולה לטעות. מומלץ לאמת מול המקור.
      </p>

      {turns.length === 0 && !loading && !error && (
        <>
          <HowItWorks />
          <RecentConversations onPick={(id) => void hydrateAndLoad(id, setConversationId, setTurns)} />
        </>
      )}
    </>
  );
}

// Helper: load a previous conversation when the user clicks one in the
// "recent" list. Replaces the URL so refresh keeps it.
async function hydrateAndLoad(
  id: string,
  setConversationId: (id: string | null) => void,
  setTurns: (t: ChatTurn[]) => void
) {
  try {
    const conv = await api.getConversation(id);
    setConversationId(conv.id);
    const hydrated: ChatTurn[] = conv.turns.map((t) => ({
      query_id: t.query_id,
      conversation_id: conv.id,
      turn_index: t.turn_index ?? 0,
      mode: t.mode,
      question: t.question,
      answer: t.answer || "",
      confidence: t.confidence || "",
      sources: t.sources.map((s) => ({
        chunk_id: s.chunk_id,
        document_filename: s.document_filename,
        section_path: s.section_path,
        text: "",
      })),
      references: [],
      unverified_reference_count: 0,
      retrieval_debug: null,
      candidate_docs: [],
      clarifying_message: t.mode === "clarify" ? t.answer : null,
      served_from: t.mode === "clarify" ? "clarify" : "llm",
      answer_annotations: [],
      feedback: t.feedback === "positive" || t.feedback === "negative" ? t.feedback : null,
      failure_mode: null,
      promoted: false,
      promoting: false,
      retrying: false,
      just_retried: false,
    }));
    setTurns(hydrated);
  } catch {
    // If the conversation can't be loaded, silently no-op — the user can
    // still start a fresh one from the composer.
  }
}

// ─── Annotated answer ──────────────────────────────────────────────────

function AnnotatedAnswer({
  text,
  annotations,
  onAddCandidate,
}: {
  text: string;
  annotations: AnswerAnnotation[];
  onAddCandidate: (term: string) => void;
}) {
  if (!annotations || annotations.length === 0) {
    return <>{text}</>;
  }
  // Non-overlapping, sorted by start (backend guarantees this, but be defensive).
  const sorted = [...annotations]
    .filter((a) => a.start >= 0 && a.end <= text.length && a.end > a.start)
    .sort((a, b) => a.start - b.start);
  const parts: ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((a, i) => {
    if (a.start < cursor) return; // overlap safety
    if (a.start > cursor) parts.push(text.slice(cursor, a.start));
    const segment = text.slice(a.start, a.end);
    if (a.kind === "known") {
      parts.push(
        <span
          key={`k-${i}`}
          title={a.expansion || undefined}
          className="underline decoration-dotted decoration-accent underline-offset-4 cursor-help"
        >
          {segment}
        </span>
      );
    } else {
      parts.push(
        <button
          key={`c-${i}`}
          type="button"
          onClick={() => onAddCandidate(a.text)}
          title="הוסף למילון"
          className="text-red-700 underline decoration-red-700 decoration-dashed underline-offset-4 hover:bg-red-50 rounded px-0.5"
        >
          {segment}
        </button>
      );
    }
    cursor = a.end;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

async function promptAddToLexicon(term: string) {
  const expansion = window.prompt(
    `הוספה למילון: "${term}"\n\nמה ההסבר / ההרחבה של המונח?`,
    ""
  );
  if (!expansion || !expansion.trim()) return;
  try {
    await api.createLexicon({ term, expansion: expansion.trim() });
    window.alert(`"${term}" נוסף למילון.`);
  } catch (e) {
    window.alert(`שגיאה בהוספה למילון: ${(e as Error).message}`);
  }
}

// ─── Report a support issue ────────────────────────────────────────────
// Free-form note from the user → email to Tal with full session context.
// Server-side lookup means the client only needs to send the query_id.

function ReportSupportButton({ queryId }: { queryId: string }) {
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const send = async () => {
    const note = window.prompt(
      "מה קרה? כתוב בקצרה את הבעיה — התשובה, השאלה וקישור לשיחה יישלחו יחד עם ההודעה.",
      ""
    );
    if (note === null) return; // user cancelled
    setSending(true);
    try {
      await api.reportSupport(queryId, note);
      setSent(true);
    } catch (e) {
      window.alert(`שליחת הדיווח נכשלה: ${(e as Error).message}`);
    } finally {
      setSending(false);
    }
  };
  if (sent) {
    return (
      <span className="px-3 py-2 text-xs text-ink-soft">
        ✓ הדיווח נשלח
      </span>
    );
  }
  return (
    <button
      onClick={send}
      disabled={sending}
      title="שולח מייל לצוות עם השאלה, התשובה, וקישור לשיחה"
      className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold border border-warning text-warning bg-white hover:bg-warning hover:text-white transition disabled:opacity-50"
    >
      {sending ? "שולח…" : <><span>דווח בעיה</span><span aria-hidden>⚑</span></>}
    </button>
  );
}

/* Small ghost action under each chat bubble — copies that bubble's text. */
function CopyLine({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard blocked — nothing useful to say */
        }
      }}
      className="inline-flex items-center gap-1.5 text-[11px] text-ink-soft hover:text-accent transition"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="2" />
        <path d="M5 15V5a2 2 0 0 1 2-2h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <span>{copied ? "הועתק" : "העתק"}</span>
    </button>
  );
}

function PlusCircle() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
      <path d="M12 8v8M8 12h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* Grey pill used for doc-type / section-number tags in references. */
function TagPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center px-2 py-1 rounded-md bg-line text-ink-soft font-rubik text-xs">
      {children}
    </span>
  );
}

/* Small teal-outlined "פתח מקור" button — DS Teal Primary. */
function OpenSourceButton({
  documentId,
  onClick,
}: {
  documentId: string;
  onClick?: (e: React.MouseEvent) => void;
}) {
  return (
    <a
      href={documentFileUrl(documentId)}
      target="_blank"
      rel="noreferrer noopener"
      onClick={onClick}
      title="פתח את קובץ המקור"
      className="shrink-0 inline-flex items-center gap-1.5 border border-turquoise text-turquoise bg-white px-3 py-1.5 rounded-md font-rubik font-semibold text-xs hover:bg-turquoise hover:text-white transition"
    >
      <ExternalLinkIcon />
      <span>פתח מקור</span>
    </a>
  );
}

function ExternalLinkIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M14 4h6v6M20 4L10 14M20 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Turn view ─────────────────────────────────────────────────────────

function TurnView({
  turn,
  onFeedback,
  onPickCandidate,
}: {
  turn: ChatTurn;
  onFeedback: (kind: "positive" | "negative") => void;
  onPickCandidate: (doc: string) => void;
}) {
  return (
    <div className="animate-fade-up space-y-3">
      {/* User bubble — justify-start puts it on the RIGHT under RTL. */}
      <div className="flex justify-start">
        <div className="max-w-[80%] rounded-[12px] bg-turquoise/10 px-4 py-3 text-base text-ink whitespace-pre-wrap leading-relaxed">
          {turn.question}
        </div>
      </div>
      <div className="flex justify-start">
        <CopyLine text={turn.question} />
      </div>

      {/* Assistant side — justify-end puts it on the LEFT under RTL. */}
      <div className="flex justify-end">
        <div className="w-full max-w-[92%] space-y-4">
          {turn.just_retried && (
            <div className="px-3 py-2 bg-surface border-r-4 border-accent text-sm text-ink">
              התשובה הקודמת הוסרה מהמטמון. הנה ניסיון חדש מבוסס מקורות.
            </div>
          )}

          {/* Confidence + cache badge */}
          <div className="flex items-center gap-4 flex-wrap">
            <span
              className={`text-[11px] tracking-[0.25em] uppercase font-bold ${
                turn.confidence === "confident"
                  ? "text-accent"
                  : turn.confidence === "uncertain"
                  ? "text-warning-dark"
                  : turn.mode === "clarify"
                  ? "text-accent"
                  : "text-ink-soft"
              }`}
            >
              {confidenceLabel[turn.confidence] || turn.confidence}
            </span>
            {turn.served_from === "hitl_cache" && (
              <span className="text-[10px] tracking-[0.2em] uppercase text-ink-soft border-r border-line-strong pr-3">
                מהמטמון המאושר
              </span>
            )}
          </div>

          {/* The answer text — same prominent treatment for both answer and
              clarify turns. The clarify mode just has no sources/share below.
              Refused answers get a different treatment further below. */}
          {turn.confidence !== "refused" && (
            <>
              <article className="rounded-[12px] bg-[#f4f4f5] px-5 py-4">
                <p className={`whitespace-pre-wrap text-ink leading-relaxed ${
                  turn.mode === "clarify"
                    ? "font-display text-base md:text-lg"
                    : "font-display text-base md:text-lg"
                }`}>
                  <AnnotatedAnswer
                    text={turn.answer}
                    annotations={turn.answer_annotations}
                    onAddCandidate={promptAddToLexicon}
                  />
                </p>
              </article>
              <div className="flex justify-end">
                <CopyLine text={turn.answer} />
              </div>
            </>
          )}

          {/* Refused turn — the answer speaks for itself, no framing copy.
              Give the user a next step and the option to flag the case to
              super-admin (corpus may know). */}
          {turn.confidence === "refused" && (
            <article className="border-2 border-ink bg-surface p-6 md:p-8">
              <p className="font-display text-xl md:text-2xl text-ink leading-relaxed">
                {turn.answer}
              </p>
              {turn.feedback === null && !turn.retrying && (
                <div className="mt-5 flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => onFeedback("positive")}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold border border-success text-success bg-white hover:bg-success hover:text-white transition"
                    title="הסירוב היה נכון — הנושא באמת מחוץ למאגר"
                  >
                    <span>צדקת שסירבת</span>
                    <span aria-hidden>✓</span>
                  </button>
                  <button
                    onClick={() => onFeedback("negative")}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold border border-danger text-danger bg-white hover:bg-danger hover:text-white transition"
                    title="הקורפוס יודע את התשובה — המערכת פשוט לא מצאה. יופיע בתור הבאגים של המנהל."
                  >
                    <span>התשובה קיימת במסמכים</span>
                    <span aria-hidden>✗</span>
                  </button>
                  <ReportSupportButton queryId={turn.query_id} />
                </div>
              )}
              {turn.feedback === "positive" && (
                <div className="mt-4 px-3 py-2 bg-surface border-r-4 border-ink text-sm text-ink">
                  ✓ סומן — סירוב נכון.
                </div>
              )}
              {turn.feedback === "negative" && (
                <div className="mt-4 px-3 py-2 bg-line/40 border-r-4 border-accent text-sm text-ink">
                  ✗ דווח למנהל. המערכת תיבחן ותעודכן.
                </div>
              )}
            </article>
          )}

          {/* Clarify mode: render candidate docs as one-click follow-ups. */}
          {turn.mode === "clarify" && turn.candidate_docs.length > 0 && (
            <div className="border border-line p-3 bg-surface">
              <div className="text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold mb-2">
                המסמכים שעולים בראש
              </div>
              <div className="flex flex-wrap gap-2">
                {turn.candidate_docs.map((doc) => (
                  <button
                    key={doc}
                    onClick={() => onPickCandidate(doc)}
                    className="px-3 py-1.5 text-sm border border-line-strong hover:border-accent hover:text-accent transition"
                  >
                    {doc}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-ink-soft mt-2 leading-relaxed">
                לחיצה ממלאת את ההמשך עם המסמך שבחרת — אפשר גם פשוט להמשיך לכתוב.
              </p>
            </div>
          )}

          {/* Answer-mode interactions: two feedback buttons + share. */}
          {turn.mode === "answer" && turn.confidence !== "refused" && (
            <>
              {turn.feedback === null && !turn.retrying && (
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => onFeedback("positive")}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold border border-success text-success bg-white hover:bg-success hover:text-white transition"
                  >
                    <span>תשובה טובה</span>
                    <span aria-hidden>✓</span>
                  </button>
                  <button
                    onClick={() => onFeedback("negative")}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold border border-danger text-danger bg-white hover:bg-danger hover:text-white transition"
                    title="הקורפוס יודע את התשובה — המערכת פשוט לא מצאה. יופיע בתור הבאגים של המנהל."
                  >
                    <span>תשובה שגויה</span>
                    <span aria-hidden>✗</span>
                  </button>
                  <ReportSupportButton queryId={turn.query_id} />
                </div>
              )}
              {turn.feedback === "positive" && (
                <div className="px-3 py-2 bg-surface border-r-4 border-ink text-sm text-ink">
                  ✓ סומן כתשובה טובה ונשמר לספריית התשובות המאושרות.
                </div>
              )}
              {turn.feedback === "negative" && (
                <div className="px-3 py-2 bg-surface border-r-4 border-accent text-sm text-ink">
                  ✗ סומן לבדיקה. המנהל יקבל התראה ויבחן את מקורות השליפה.
                </div>
              )}
              {turn.retrying && (
                <div className="px-3 py-2 bg-surface border-r-4 border-line-strong text-sm text-ink-soft animate-pulse">
                  מחפש שוב…
                </div>
              )}
              <ShareActions
                question={turn.question}
                answer={turn.answer}
                references={turn.references}
              />
            </>
          )}

          {turn.mode === "answer" && turn.references && turn.references.length > 0 && (
            <div>
              <div className="font-rubik font-bold text-base tracking-[0.15em] text-turquoise mb-3 flex items-center gap-3">
                <span>סימוכין</span>
                <span className="flex-1 h-px bg-line" />
              </div>
              <div className="space-y-2">
                {turn.references.map((r, i) => {
                  const openable = r.document_id && r.has_file;
                  return (
                    <div
                      key={`${r.title}-${r.section_number}-${i}`}
                      className="flex items-start gap-3 p-3 bg-white border border-line rounded-md"
                    >
                      {openable && r.document_id && (
                        <OpenSourceButton documentId={r.document_id} />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-2 justify-end">
                          {r.section_number && <TagPill>{r.section_number}</TagPill>}
                          {r.source_type && <TagPill>{r.source_type}</TagPill>}
                        </div>
                        <div className="font-semibold text-ink text-right">{r.title}</div>
                        {r.excerpt && (
                          <blockquote className="mt-2 text-sm text-ink-soft leading-relaxed text-right">
                            {r.excerpt}
                          </blockquote>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              {turn.unverified_reference_count > 0 && (
                <p className="mt-2 text-xs text-ink-soft">
                  {turn.unverified_reference_count === 1
                    ? "סימוכין אחד לא נמצא במסמכים שנשלפו ולכן לא מוצג."
                    : `${turn.unverified_reference_count} סימוכין לא נמצאו במסמכים שנשלפו ולכן אינם מוצגים.`}
                </p>
              )}
            </div>
          )}

          {turn.mode === "answer" && turn.sources.length > 0 && (
            <details className="mt-2">
              <summary className="px-1 py-2 cursor-pointer text-turquoise font-rubik font-bold text-base tracking-[0.15em] hover:text-turquoise-dark transition flex items-center gap-3">
                <span>קטעי טקסט שנשלפו ({turn.sources.length})</span>
                <span className="flex-1 h-px bg-line" />
                <ChevronDownIcon />
              </summary>
              <div className="mt-3 space-y-2">
                {turn.sources.map((s, i) => (
                  <details key={s.chunk_id} className="bg-white border border-line rounded-md">
                    <summary className="cursor-pointer flex items-start gap-3 p-3 hover:bg-line/20 transition rounded-md">
                      {s.has_file && s.document_id && (
                        <OpenSourceButton
                          documentId={s.document_id}
                          onClick={(e) => e.stopPropagation()}
                        />
                      )}
                      <div className="flex-1 min-w-0 text-right">
                        <div className="flex items-center gap-2 justify-end">
                          <span className="font-semibold text-ink">{s.document_filename}</span>
                          <span className="inline-flex items-center justify-center min-w-6 h-6 px-2 rounded-full bg-turquoise/10 text-turquoise font-rubik font-bold text-xs">
                            {i + 1}
                          </span>
                        </div>
                        {s.section_path && (
                          <div className="mt-1 flex justify-end">
                            <TagPill>{s.section_path}</TagPill>
                          </div>
                        )}
                      </div>
                    </summary>
                    <div className="px-4 py-3 border-t border-line text-xs leading-relaxed whitespace-pre-wrap text-ink-soft text-right">
                      {s.text}
                    </div>
                  </details>
                ))}
              </div>
            </details>
          )}

          {turn.retrieval_debug && <DebugPanel debug={turn.retrieval_debug} />}
        </div>
      </div>
    </div>
  );
}

// ─── Debug panel (unchanged from v0.2) ─────────────────────────────────

function DebugRow({ row }: { row: RetrievalDebugRow }) {
  const score =
    row.cosine_similarity !== undefined
      ? `cos ${row.cosine_similarity}`
      : row.ts_rank !== undefined
      ? `bm25 ${row.ts_rank}`
      : row.title_rank !== undefined
      ? `title ${row.title_rank}`
      : row.fusion_score !== undefined
      ? `fused ${row.fusion_score}`
      : row.rank !== undefined
      ? `#${row.rank}`
      : "";
  return (
    <li className="flex items-baseline gap-3 py-1.5 text-xs">
      <span className="font-mono text-ink-soft min-w-[88px] text-left">{score}</span>
      <span className="text-ink truncate flex-1">{row.document_filename}</span>
      {row.lanes && row.lanes.length > 0 && (
        <span className="font-mono text-[10px] text-accent shrink-0">
          {row.lanes.join("+")}
        </span>
      )}
      {row.section_path && (
        <span className="text-ink-soft truncate max-w-[200px]">⋅ {row.section_path}</span>
      )}
    </li>
  );
}

function DebugPanel({ debug }: { debug: RetrievalDebug | null }) {
  const [open, setOpen] = useState(false);
  if (!debug) return null;
  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="bg-white border border-stone-200 rounded-xl overflow-hidden shadow-soft"
    >
      <summary className="px-3 py-2 cursor-pointer hover:bg-stone-50 text-xs font-semibold text-ink-soft flex items-center justify-between">
        <span>פירוט שליפה (debug)</span>
        <span className="text-xs text-ink-soft">
          {debug.reranked.length} נשלפו · {debug.vector.length} וקטור · {debug.bm25.length} BM25 · {debug.title?.length ?? 0} כותרת
        </span>
      </summary>
      <div className="px-3 py-2 border-t border-stone-200 grid sm:grid-cols-2 gap-4 bg-stone-50/70">
        <div>
          <div className="text-[10px] tracking-wider uppercase text-accent font-bold mb-1">
            סופי (אחרי rerank)
          </div>
          <ul className="divide-y divide-stone-200/70">
            {debug.reranked.map((r) => (
              <DebugRow key={`r-${r.chunk_id}`} row={r} />
            ))}
          </ul>
        </div>
        <div>
          <div className="text-[10px] tracking-wider uppercase text-accent font-bold mb-1">
            וקטור (cosine)
          </div>
          <ul className="divide-y divide-stone-200/70">
            {debug.vector.map((r) => (
              <DebugRow key={`v-${r.chunk_id}`} row={r} />
            ))}
          </ul>
        </div>
        <div>
          <div className="text-[10px] tracking-wider uppercase text-accent font-bold mb-1">
            BM25 (ts_rank)
          </div>
          <ul className="divide-y divide-stone-200/70">
            {debug.bm25.map((r) => (
              <DebugRow key={`b-${r.chunk_id}`} row={r} />
            ))}
          </ul>
        </div>
        {debug.title && debug.title.length > 0 && (
          <div>
            <div className="text-[10px] tracking-wider uppercase text-accent font-bold mb-1">
              כותרת (title_search)
            </div>
            <ul className="divide-y divide-stone-200/70">
              {debug.title.map((r) => (
                <DebugRow key={`t-${r.chunk_id}`} row={r} />
              ))}
            </ul>
          </div>
        )}
        <div>
          <div className="text-[10px] tracking-wider uppercase text-accent font-bold mb-1">
            איחוד (RRF)
          </div>
          <ul className="divide-y divide-stone-200/70">
            {debug.fused.map((r) => (
              <DebugRow key={`f-${r.chunk_id}`} row={r} />
            ))}
          </ul>
        </div>
      </div>
    </details>
  );
}

// ─── ThinkingProgress (unchanged from v0.2) ────────────────────────────

const THINKING_STAGES: {
  key: SearchPipelineStage;
  label: string;
  pct: number;
  typicalMs: number;
}[] = [
  { key: "analyzing", label: "ניתוח השאלה", pct: 0, typicalMs: 800 },
  { key: "searching", label: "חיפוש בארכיון", pct: 20, typicalMs: 1500 },
  { key: "ranking", label: "דירוג מקורות", pct: 45, typicalMs: 800 },
  { key: "generating", label: "ניסוח תשובה", pct: 65, typicalMs: 8000 },
];
const FINAL_PCT = 95;

function ThinkingProgress({
  stage,
  detail,
}: {
  stage: SearchPipelineStage | null;
  detail: string | null;
}) {
  const [tick, setTick] = useState(0);
  const [stageEnteredAt, setStageEnteredAt] = useState<number>(() => Date.now());

  useEffect(() => {
    setStageEnteredAt(Date.now());
  }, [stage]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 150);
    return () => clearInterval(id);
  }, []);
  void tick;

  const stageIdx = THINKING_STAGES.findIndex((s) => s.key === stage);
  const currentIdx = stageIdx >= 0 ? stageIdx : 0;
  const current = THINKING_STAGES[currentIdx];
  const next = THINKING_STAGES[currentIdx + 1];
  const stageStartPct = current.pct;
  const stageEndPct = next ? next.pct : FINAL_PCT;

  const elapsedInStage = Date.now() - stageEnteredAt;
  const progressRatio = 1 - Math.exp(-elapsedInStage / current.typicalMs);
  const pct = stageStartPct + (stageEndPct - stageStartPct) * progressRatio;

  return (
    <section
      className="mb-6 py-4 animate-fade-up"
      role="status"
      aria-live="polite"
      aria-label="מתבצע חיפוש"
    >
      <div className="h-[3px] bg-line overflow-hidden mb-3">
        <div
          className="h-full bg-turquoise transition-[width] duration-300 ease-out"
          style={{ width: `${Math.min(pct, FINAL_PCT)}%` }}
        />
      </div>
      {/* Stage labels — H5 (Rubik Bold 16, tracking 25%) */}
      <div className="grid grid-cols-4 gap-2 font-rubik font-bold text-base uppercase tracking-[0.25em]">
        {THINKING_STAGES.map((s, i) => {
          const state = i < currentIdx ? "done" : i === currentIdx ? "active" : "pending";
          const cls =
            state === "active"
              ? "text-turquoise"
              : state === "done"
              ? "text-ink"
              : "text-line-strong";
          return (
            <span key={s.key} className={cls}>
              <span className="text-ink-soft ml-2">0{i + 1}</span>
              {s.label}
            </span>
          );
        })}
      </div>
      {detail && <div className="mt-3 text-xs text-ink-soft">{detail}</div>}
    </section>
  );
}

// ─── Share (unchanged from v0.2) ───────────────────────────────────────

const POWERED_BY = "Powered By Takanon, Organizational Memory";

function buildShareText({
  question,
  answer,
  references,
}: {
  question: string;
  answer: string;
  references: { title: string; section_number: string }[];
}): { plain: string; markdown: string } {
  const refsList = references.length
    ? references.map(
        (r) => `${r.title}${r.section_number ? ` — סעיף ${r.section_number}` : ""}`
      )
    : [];

  const plain = [
    `שאלה: ${question}`,
    "",
    `תשובה:`,
    answer,
    refsList.length ? "\nמקורות:" : "",
    ...refsList.map((r) => `• ${r}`),
    "",
    "—",
    POWERED_BY,
  ]
    .filter((l) => l !== null)
    .join("\n");

  const markdown = [
    `### ${question}`,
    "",
    answer,
    refsList.length ? "\n**מקורות:**" : "",
    ...refsList.map((r) => `- ${r}`),
    "",
    "---",
    `_${POWERED_BY}_`,
  ]
    .filter((l) => l !== null)
    .join("\n");

  return { plain, markdown };
}

function ShareActions({
  question,
  answer,
  references,
}: {
  question: string;
  answer: string;
  references: { title: string; section_number: string }[];
}) {
  const [copied, setCopied] = useState<"plain" | "markdown" | null>(null);
  const { plain, markdown } = buildShareText({ question, answer, references });

  const copyToClipboard = async (which: "plain" | "markdown") => {
    const text = which === "plain" ? plain : markdown;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      /* noop */
    }
  };

  const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(plain)}`;
  const mailtoUrl =
    `mailto:?subject=${encodeURIComponent(`תשובה לשאלה: ${question}`)}` +
    `&body=${encodeURIComponent(plain)}`;

  // Share row — light pills, no divider rule, per the chat redesign.
  return (
    <div className="pt-1">
      <div className="flex flex-wrap items-center gap-2">
        <a
          href={whatsappUrl}
          target="_blank"
          rel="noreferrer noopener"
          className="px-3 py-1.5 rounded-md text-xs bg-line/50 text-ink-soft hover:bg-line hover:text-ink transition"
        >
          Whatsapp
        </a>
        <a
          href={mailtoUrl}
          className="px-3 py-1.5 rounded-md text-xs bg-line/50 text-ink-soft hover:bg-line hover:text-ink transition"
        >
          אימייל
        </a>
        <button
          type="button"
          onClick={() => copyToClipboard("markdown")}
          className="px-3 py-1.5 rounded-md text-xs bg-line/50 text-ink-soft hover:bg-line hover:text-ink transition"
        >
          {copied === "markdown" ? "הועתק ✓" : "העתק Markdown"}
        </button>
        <button
          type="button"
          onClick={() => copyToClipboard("plain")}
          className="px-3 py-1.5 rounded-md text-xs bg-line/50 text-ink-soft hover:bg-line hover:text-ink transition"
        >
          {copied === "plain" ? "הועתק ✓" : "העתק טקסט"}
        </button>
      </div>
    </div>
  );
}

// ─── Recent conversations sidebar (replaces "recent questions") ────────

function RecentConversations({ onPick }: { onPick: (id: string) => void }) {
  const [convs, setConvs] = useState<ConversationSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listConversations(8)
      .then((cs) => {
        if (!cancelled) setConvs(cs);
      })
      .catch(() => {
        if (!cancelled) setConvs([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (convs === null || convs.length === 0) return null;

  return (
    <section className="mt-10 animate-fade-up">
      <div className="text-[11px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-4 flex items-center gap-3">
        <span>שיחות אחרונות</span>
        <span className="flex-1 h-px bg-line" />
      </div>
      {/* Rows are separate boxes now: 722px max, 8px gap, 8px radius — the
          shared container border and hairline dividers are gone. */}
      <ul className="flex flex-col gap-2 w-full max-w-[722px]">
        {convs.map((c, i) => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => onPick(c.id)}
              className="group w-full text-right px-4 py-3 rounded-[8px] border border-line bg-white hover:bg-line/40 transition flex items-baseline gap-4 text-sm text-ink"
            >
              <span className="font-mono text-xs text-ink-soft group-hover:text-accent transition w-6 shrink-0">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="flex-1 truncate">
                {c.title || c.last_user_question || "(שיחה ללא כותרת)"}
              </span>
              <span className="text-xs text-ink-soft shrink-0">
                {c.turn_count} {c.turn_count === 1 ? "תור" : "תורים"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function HowItWorks() {
  const steps: { title: string; body: React.ReactNode }[] = [
    {
      title: "תחילת שיחה",
      body: (
        <>
          שאל שאלה רגילה. אם משהו חסר כדי לתת תשובה מדויקת — המערכת תבקש הבהרה
          קצרה לפני שתחפש.
        </>
      ),
    },
    {
      title: "הבהרה",
      body: (
        <>
          לדוגמה: "האם אתה חבר הקיבוץ או יורש בלבד? הכוונה לתקנון השיוך או
          להסדר רישום הדירות?". תוכל ללחוץ על אחת ההצעות או לכתוב חופשי.
        </>
      ),
    },
    {
      title: "אחזור עם הקשר",
      body: (
        <>
          המערכת קוראת את כל ההיסטוריה של השיחה, מאתרת את הסעיפים הרלוונטיים
          לפי משמעות ולפי מילים, ומדרגת אותם.
        </>
      ),
    },
    {
      title: "תשובה מצוטטת",
      body: (
        <>
          הקטעים הנבחרים נשלחים ל-Claude שמנסח תשובה תוך ציטוט המקור. אם אין
          מספיק עוגן במסמכים — המערכת תאמר ולא תמציא.
        </>
      ),
    },
  ];

  return (
    <section className="mt-4 animate-fade-up">
      {/* H5 — Rubik Bold 16, tracking 25% (Klaser DS) */}
      <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-4 flex items-center gap-3">
        <span>איך זה עובד</span>
        <span className="flex-1 h-px bg-line" />
      </div>

      {/* Body — Heebo Regular 18 */}
      <p className="font-sans text-lg leading-relaxed text-[#525252] mb-6 max-w-2xl">
        זו לא חיפוש חד-פעמי — זו שיחה. כשאתה מבהיר את הכוונה, המערכת לומדת
        מההמשך ועונה טוב יותר בפעם הבאה.
      </p>

      {/* Cards per Figma: 374px wide, 24px padding, 8px item gap, 12px radius,
          3px teal-20% border on white. `items-start` is the RTL equivalent of
          Figma's `align-items: flex-end` — both put content on the right edge. */}
      <ol className="grid md:grid-cols-2 gap-4">
        {steps.map((s, i) => (
          <li
            key={s.title}
            className="flex flex-col items-start gap-2 w-full max-w-[374px] p-6 rounded-[12px] border-[3px] border-turquoise/20 bg-white"
          >
            <div className="flex items-baseline gap-3">
              <span className="font-mono text-accent font-bold text-sm">0{i + 1}</span>
              <h3 className="font-display font-bold text-ink">{s.title}</h3>
            </div>
            <p className="text-sm text-ink-soft leading-relaxed">{s.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
