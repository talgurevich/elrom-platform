import { useEffect, useRef, useState } from "react";
import {
  api,
  documentFileUrl,
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
  retrieval_debug: RetrievalDebug | null;
  candidate_docs: string[];
  clarifying_message: string | null;
  served_from: string;
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
    retrieval_debug: r.retrieval_debug,
    candidate_docs: r.candidate_docs || [],
    clarifying_message: r.clarifying_message,
    served_from: r.served_from,
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
          retrieval_debug: null,
          candidate_docs: [],
          clarifying_message: t.mode === "clarify" ? t.answer : null,
          served_from: t.mode === "clarify" ? "clarify" : "llm",
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
    setQuestion("");
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
          <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold">
            שיחה
          </div>
          {(turns.length > 0 || conversationId) && (
            <button
              onClick={startNewConversation}
              className="text-xs text-ink-soft hover:text-accent transition underline underline-offset-4"
              title="התחל שיחה חדשה — מנקה את ההקשר"
            >
              שיחה חדשה +
            </button>
          )}
        </div>
        {turns.length === 0 ? (
          <>
            <h1 className="font-display text-5xl md:text-6xl font-black text-ink leading-[0.95]">
              זיכרון ארגוני
              <br />
              <span className="text-ink-soft">בשיחה.</span>
            </h1>
            <p className="text-ink-soft mt-5 text-base max-w-xl leading-relaxed">
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
      <form
        onSubmit={submit}
        className="mt-6 sticky bottom-4 bg-surface border-2 border-ink p-3 shadow-soft"
      >
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
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
        <div className="mt-2 flex items-center gap-3 flex-wrap">
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="px-6 py-2 bg-accent hover:bg-accent-dark text-surface font-bold tracking-wide disabled:opacity-40 disabled:cursor-not-allowed transition"
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
          <span className="text-xs text-ink-soft">Cmd/Ctrl + Enter</span>
        </div>
      </form>

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
      retrieval_debug: null,
      candidate_docs: [],
      clarifying_message: t.mode === "clarify" ? t.answer : null,
      served_from: t.mode === "clarify" ? "clarify" : "llm",
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
    <div className="animate-fade-up">
      {/* User bubble */}
      <div className="flex gap-3 mb-3">
        <div className="text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold pt-1 w-16 shrink-0">
          את/ה
        </div>
        <div className="text-base text-ink whitespace-pre-wrap leading-relaxed flex-1">
          {turn.question}
        </div>
      </div>

      {/* Assistant bubble */}
      <div className="flex gap-3">
        <div className="text-[10px] tracking-[0.2em] uppercase text-accent font-bold pt-1 w-16 shrink-0">
          המערכת
        </div>
        <div className="flex-1 space-y-4">
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
                  ? "text-amber-700"
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
            <article className="relative bg-surface">
              <div className="absolute -right-1 top-0 bottom-0 w-1 bg-accent" />
              <div className="pr-5 py-1">
                <p className={`whitespace-pre-wrap text-ink leading-relaxed ${
                  turn.mode === "clarify"
                    ? "font-display text-lg md:text-xl"
                    : "font-display text-xl md:text-2xl"
                }`}>
                  {turn.answer}
                </p>
              </div>
            </article>
          )}

          {/* Refused turn — reframed as integrity. The system chose not to
              answer rather than guess. Give the user a next step and the
              option to flag the case to super-admin (corpus may know). */}
          {turn.confidence === "refused" && (
            <article className="border-2 border-ink bg-surface p-6 md:p-8">
              <div className="text-[11px] tracking-[0.3em] uppercase text-accent font-bold mb-3">
                המערכת בחרה לא לענות
              </div>
              <p className="font-display text-xl md:text-2xl text-ink leading-relaxed">
                {turn.answer}
              </p>
              <p className="mt-5 text-sm text-ink-soft leading-relaxed">
                המערכת מעדיפה להודות שאין לה תשובה מבוססת על פני לענות בניחוש.
                אם הנושא באמת אמור להיות במסמכי הארגון —{" "}
                <button
                  onClick={() => onFeedback("negative")}
                  disabled={turn.feedback !== null}
                  className="underline underline-offset-4 hover:text-accent disabled:opacity-60 disabled:pointer-events-none"
                >
                  דווחו למנהל
                </button>{" "}
                כדי שיבדוק את השליפה.
              </p>
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
                    className="px-4 py-2 text-sm font-semibold border-2 border-ink bg-surface hover:bg-ink hover:text-surface transition"
                  >
                    ✓ תשובה טובה
                  </button>
                  <button
                    onClick={() => onFeedback("negative")}
                    className="px-4 py-2 text-sm font-semibold border-2 border-accent text-accent bg-surface hover:bg-accent hover:text-surface transition"
                    title="הקורפוס יודע את התשובה — המערכת פשוט לא מצאה. יופיע בתור הבאגים של המנהל."
                  >
                    ✗ התשובה שגויה — הקורפוס יודע
                  </button>
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
              <div className="text-[11px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-2 flex items-center gap-3">
                <span>סימוכין</span>
                <span className="flex-1 h-px bg-line" />
              </div>
              <div className="grid gap-px bg-line border border-line">
                {turn.references.map((r, i) => {
                  // Try to match the reference title to a source's document so
                  // we can offer "open source PDF" straight from the citation.
                  const matched = turn.sources.find(
                    (s) => s.document_filename === r.title && s.has_file && s.document_id
                  );
                  return (
                    <div
                      key={`${r.title}-${r.section_number}-${i}`}
                      className="p-3 bg-surface"
                    >
                      <div className="flex items-baseline gap-3 mb-1.5 flex-wrap">
                        {matched?.document_id ? (
                          <a
                            href={documentFileUrl(matched.document_id)}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="font-semibold text-ink hover:text-accent underline underline-offset-4 decoration-line-strong hover:decoration-accent"
                            title="פתח את קובץ המקור"
                          >
                            {r.title}
                          </a>
                        ) : (
                          <span className="font-semibold text-ink">{r.title}</span>
                        )}
                        {r.section_number && (
                          <span className="text-xs text-accent font-mono tracking-tight">
                            {r.section_number}
                          </span>
                        )}
                        {r.source_type && (
                          <span className="text-[10px] tracking-[0.2em] uppercase text-ink-soft mr-auto">
                            {r.source_type}
                          </span>
                        )}
                        {matched?.document_id && (
                          <a
                            href={documentFileUrl(matched.document_id)}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="text-[10px] tracking-[0.2em] uppercase text-accent font-bold hover:underline"
                          >
                            פתח מקור ↗
                          </a>
                        )}
                      </div>
                      {r.excerpt && (
                        <blockquote className="text-sm text-ink-soft leading-relaxed">
                          {r.excerpt}
                        </blockquote>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {turn.mode === "answer" && turn.sources.length > 0 && (
            <details className="border border-line">
              <summary className="px-3 py-2 cursor-pointer hover:bg-line/40 text-[11px] tracking-[0.25em] uppercase font-bold text-ink-soft">
                קטעי טקסט שנשלפו ({turn.sources.length})
              </summary>
              <div className="border-t border-line grid gap-px bg-line">
                {turn.sources.map((s, i) => (
                  <details key={s.chunk_id} className="bg-surface">
                    <summary className="px-3 py-2 cursor-pointer hover:bg-line/40 text-sm flex items-baseline gap-3">
                      <span className="font-mono text-accent">[{i + 1}]</span>
                      <span className="text-ink">{s.document_filename}</span>
                      {s.section_path && (
                        <span className="text-ink-soft font-mono text-xs">
                          {s.section_path}
                        </span>
                      )}
                      {s.has_file && s.document_id && (
                        <a
                          href={documentFileUrl(s.document_id)}
                          target="_blank"
                          rel="noreferrer noopener"
                          onClick={(e) => e.stopPropagation()}
                          className="mr-auto text-[10px] tracking-[0.2em] uppercase text-accent font-bold hover:underline"
                          title="פתח את קובץ המקור"
                        >
                          פתח מקור ↗
                        </a>
                      )}
                    </summary>
                    <div className="px-3 py-2 border-t border-line text-xs leading-relaxed whitespace-pre-wrap text-ink-soft">
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
      : row.fusion_score !== undefined
      ? `fused ${row.fusion_score}`
      : row.rank !== undefined
      ? `#${row.rank}`
      : "";
  return (
    <li className="flex items-baseline gap-3 py-1.5 text-xs">
      <span className="font-mono text-ink-soft min-w-[88px] text-left">{score}</span>
      <span className="text-ink truncate flex-1">{row.document_filename}</span>
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
          {debug.reranked.length} נשלפו · {debug.vector.length} וקטור · {debug.bm25.length} BM25
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
      className="mb-6 py-4 border-y-2 border-ink animate-fade-up"
      role="status"
      aria-live="polite"
      aria-label="מתבצע חיפוש"
    >
      <div className="h-[3px] bg-line overflow-hidden mb-3">
        <div
          className="h-full bg-accent transition-[width] duration-300 ease-out"
          style={{ width: `${Math.min(pct, FINAL_PCT)}%` }}
        />
      </div>
      <div className="grid grid-cols-4 gap-2 text-[11px] tracking-wider uppercase font-bold">
        {THINKING_STAGES.map((s, i) => {
          const state = i < currentIdx ? "done" : i === currentIdx ? "active" : "pending";
          const cls =
            state === "active"
              ? "text-accent"
              : state === "done"
              ? "text-ink"
              : "text-line-strong";
          return (
            <span key={s.key} className={cls}>
              <span className="text-ink-soft font-mono ml-2">0{i + 1}</span>
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

const POWERED_BY = "Powered by זכרון ארגוני";

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

  return (
    <div className="pt-2 border-t border-line">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-ink-soft ml-2">שלח / העתק:</span>
        <a
          href={whatsappUrl}
          target="_blank"
          rel="noreferrer noopener"
          className="px-3 py-1.5 text-sm border border-line-strong hover:border-ink hover:bg-surface text-ink-soft hover:text-ink transition"
        >
          WhatsApp
        </a>
        <a
          href={mailtoUrl}
          className="px-3 py-1.5 text-sm border border-line-strong hover:border-ink hover:bg-surface text-ink-soft hover:text-ink transition"
        >
          אימייל
        </a>
        <button
          type="button"
          onClick={() => copyToClipboard("markdown")}
          className="px-3 py-1.5 text-sm border border-line-strong hover:border-ink hover:bg-surface text-ink-soft hover:text-ink transition"
        >
          {copied === "markdown" ? "הועתק ✓" : "העתק Markdown"}
        </button>
        <button
          type="button"
          onClick={() => copyToClipboard("plain")}
          className="px-3 py-1.5 text-sm border border-line-strong hover:border-ink hover:bg-surface text-ink-soft hover:text-ink transition"
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
      <ul className="border border-line">
        {convs.map((c, i) => (
          <li key={c.id} className={i > 0 ? "border-t border-line" : ""}>
            <button
              type="button"
              onClick={() => onPick(c.id)}
              className="group w-full text-right px-4 py-3 hover:bg-line/40 transition flex items-baseline gap-4 text-sm text-ink"
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
      <div className="text-[11px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-4 flex items-center gap-3">
        <span>איך זה עובד</span>
        <span className="flex-1 h-px bg-line" />
      </div>

      <p className="text-sm text-ink-soft leading-relaxed mb-6 max-w-2xl">
        זו לא חיפוש חד-פעמי — זו שיחה. כשאתה מבהיר את הכוונה, המערכת לומדת
        מההמשך ועונה טוב יותר בפעם הבאה.
      </p>

      <ol className="grid md:grid-cols-2 gap-px bg-line border border-line">
        {steps.map((s, i) => (
          <li key={s.title} className="bg-surface p-5">
            <div className="flex items-baseline gap-3 mb-2">
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
