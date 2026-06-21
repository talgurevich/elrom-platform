import { useEffect, useState } from "react";
import {
  api,
  type FailureMode,
  type RetrievalDebugRow,
  type SearchPipelineStage,
  type SearchResponse,
} from "../lib/api";

const confidenceLabel: Record<string, string> = {
  confident: "תשובה מבוססת",
  uncertain: "תשובה חלקית",
  refused: "אין תשובה במאגר",
};

const failureLabels: Record<FailureMode, string> = {
  retrieval_miss: "השליפה החטיאה",
  wrong_generation: "הניסוח שגוי",
  other: "אחר",
};

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

function DebugPanel({ debug }: { debug: SearchResponse["retrieval_debug"] }) {
  const [open, setOpen] = useState(false);
  if (!debug) return null;
  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="bg-white border border-stone-200 rounded-xl overflow-hidden shadow-soft"
    >
      <summary className="px-4 py-3 cursor-pointer hover:bg-stone-50 text-sm font-semibold text-ink-soft flex items-center justify-between">
        <span>פירוט שליפה (debug)</span>
        <span className="text-xs text-ink-soft">
          {debug.reranked.length} נשלפו · {debug.vector.length} וקטור · {debug.bm25.length} BM25
        </span>
      </summary>
      <div className="px-4 py-3 border-t border-stone-200 grid sm:grid-cols-2 gap-6 bg-stone-50/70">
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

export default function Search() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<"positive" | "negative" | null>(null);
  const [failureMode, setFailureMode] = useState<FailureMode | null>(null);
  const [promoted, setPromoted] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [justRetried, setJustRetried] = useState(false);
  const [stage, setStage] = useState<SearchPipelineStage | null>(null);
  const [stageDetail, setStageDetail] = useState<string | null>(null);

  const runSearch = async (q: string) => {
    if (!q.trim()) return;
    setQuestion(q);
    setLoading(true);
    setError(null);
    setResult(null);
    setFeedback(null);
    setFailureMode(null);
    setPromoted(false);
    setJustRetried(false);
    setStage(null);
    setStageDetail(null);
    try {
      const fresh = await api.searchStream(q, (ev) => {
        if (ev.type === "stage") setStage(ev.stage);
        else if (ev.type === "detail") setStageDetail(ev.text);
      });
      setResult(fresh);
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

  const submitFeedback = async (kind: "positive" | "negative") => {
    if (!result) return;
    setFeedback(kind);
    try {
      const resp = await api.feedback(result.query_id, kind);
      // If the user 👎'd an answer that came from the authoritative cache,
      // the backend retires it. Immediately re-run the same question so the
      // user sees a fresh attempt instead of having to re-type and re-ask.
      if (kind === "negative" && resp.cached_answer_retired) {
        setRetrying(true);
        try {
          const fresh = await api.search(question);
          setResult(fresh);
          setFeedback(null);
          setFailureMode(null);
          setPromoted(false);
          setJustRetried(true);
        } finally {
          setRetrying(false);
        }
      }
    } catch (err) {
      setFeedback(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const promoteToGolden = async () => {
    if (!result) return;
    setPromoting(true);
    try {
      await api.promoteQueryToGolden(result.query_id);
      setPromoted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPromoting(false);
    }
  };

  const tagFailure = async (mode: FailureMode) => {
    if (!result) return;
    setFailureMode(mode);
    setFeedback("negative");
    try {
      await api.tagFailureMode(result.query_id, mode);
    } catch (err) {
      setFailureMode(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <>
      <header className="mb-10">
        <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
          חיפוש
        </div>
        <h1 className="font-display text-5xl md:text-6xl font-black text-ink leading-[0.95]">
          זיכרון ארגוני
          <br />
          <span className="text-ink-soft">נגיש מיידית.</span>
        </h1>
        <p className="text-ink-soft mt-5 text-base max-w-xl leading-relaxed">
          שאל שאלה בעברית. המערכת תקרא את כל התקנונים, תאתר את המקורות
          הרלוונטיים ביותר, ותחזיר תשובה מבוססת ציטוטים.
        </p>
      </header>

      <form onSubmit={submit} className="mb-10">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              void runSearch(question);
            }
          }}
          placeholder="לדוגמה: מה הוחלט בעניין קדימות לקומה שנייה?"
          rows={3}
          className="w-full px-4 py-3 bg-surface border-2 border-ink focus:border-accent outline-none text-base resize-none transition placeholder:text-ink-soft/70"
        />
        <div className="mt-4 flex items-center gap-3 flex-wrap">
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="px-8 py-3 bg-accent hover:bg-accent-dark text-surface font-bold tracking-wide disabled:opacity-40 disabled:cursor-not-allowed transition min-w-[120px]"
          >
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <span className="inline-block w-2.5 h-2.5 bg-surface animate-pulse" />
                <span>חושב</span>
              </span>
            ) : (
              "שאל"
            )}
          </button>
          <span className="text-xs text-ink-soft">
            Cmd/Ctrl + Enter לשליחה מהירה
          </span>
        </div>
      </form>

      {loading && <ThinkingProgress stage={stage} detail={stageDetail} />}

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-900 text-sm whitespace-pre-wrap">
          {error}
        </div>
      )}

      {/* Virgin-state explainer + recent-questions list. Both shown only before
          the first query lands; hidden the moment a result / error / loading
          state appears. */}
      {!result && !error && !loading && (
        <>
          <HowItWorks />
          <RecentQuestions onPick={(q) => void runSearch(q)} />
        </>
      )}

      {result && (
        <div className="space-y-6 animate-fade-up">
          {result.near_misses && result.near_misses.length > 0 && (
            <div className="border-2 border-accent bg-surface">
              <div className="px-4 py-2 bg-accent text-surface text-[11px] tracking-[0.2em] uppercase font-bold">
                קיימת תשובה מאושרת קרובה בארכיון
              </div>
              <div>
                {result.near_misses.map((nm) => (
                  <details
                    key={nm.authoritative_answer_id}
                    className="border-t border-line first:border-t-0"
                  >
                    <summary className="px-4 py-3 cursor-pointer text-sm hover:bg-line/40">
                      <span className="text-accent font-bold font-mono">
                        {Math.round(nm.similarity * 100)}%
                      </span>
                      <span className="text-ink mr-3">{nm.canonical_question}</span>
                    </summary>
                    <div className="px-4 py-3 border-t border-line text-sm leading-relaxed whitespace-pre-wrap text-ink-soft">
                      {nm.answer}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}
          {/* 0. Retry banner (after auto-retry from 👎 on cached answer) */}
          {justRetried && (
            <div className="px-4 py-3 bg-surface border-r-4 border-accent text-sm text-ink">
              התשובה הקודמת הוסרה מהמטמון. הנה ניסיון חדש מבוסס מקורות.
            </div>
          )}

          {/* 1. Confidence label — flat, no pill */}
          <div className="flex items-center gap-4">
            <span
              className={`text-[11px] tracking-[0.25em] uppercase font-bold ${
                result.confidence === "confident"
                  ? "text-accent"
                  : result.confidence === "uncertain"
                  ? "text-amber-700"
                  : "text-ink-soft"
              }`}
            >
              {confidenceLabel[result.confidence] || result.confidence}
            </span>
            {result.served_from === "hitl_cache" && (
              <span className="text-[10px] tracking-[0.2em] uppercase text-ink-soft border-r border-line-strong pr-3">
                מהמטמון המאושר
              </span>
            )}
          </div>

          {/* 2. Natural-language answer — the artifact */}
          <article className="relative bg-surface">
            <div className="absolute -right-1 top-0 bottom-0 w-1 bg-accent" />
            <div className="pr-6 py-2">
              <p className="font-display text-xl md:text-2xl leading-relaxed whitespace-pre-wrap text-ink">
                {result.answer}
              </p>
            </div>

            {result.confidence !== "refused" && (
              <div className="mt-6 pt-4 border-t border-line flex flex-wrap items-center gap-2">
                <span className="text-xs text-ink-soft ml-2">
                  {retrying ? "מחפש שוב…" : "האם התשובה מדויקת?"}
                </span>
                <button
                  onClick={() => submitFeedback("positive")}
                  disabled={feedback !== null || retrying}
                  className={`px-3 py-1.5 text-sm border transition ${
                    feedback === "positive"
                      ? "bg-ink text-surface border-ink"
                      : "bg-surface border-line-strong hover:border-ink"
                  }`}
                >
                  כן
                </button>
                <button
                  onClick={() => submitFeedback("negative")}
                  disabled={feedback !== null || retrying}
                  className={`px-3 py-1.5 text-sm border transition ${
                    feedback === "negative"
                      ? "bg-accent text-surface border-accent"
                      : "bg-surface border-line-strong hover:border-accent hover:text-accent"
                  }`}
                >
                  לא
                </button>
                <button
                  onClick={promoteToGolden}
                  disabled={promoting || promoted}
                  className="px-3 py-1.5 text-sm border border-line-strong hover:border-ink hover:bg-surface disabled:opacity-50 text-ink-soft transition mr-auto"
                  title="הפוך לשאלת זהב להרצה חוזרת"
                >
                  {promoted ? "✓ נשמר כשאלת זהב" : promoting ? "..." : "סמן כשאלת זהב"}
                </button>
              </div>
            )}
          </article>

          {/* 3. Cited clauses — index-card aesthetic */}
          {result.references && result.references.length > 0 && (
            <div>
              <div className="text-[11px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-3 flex items-center gap-3">
                <span>סימוכין</span>
                <span className="flex-1 h-px bg-line" />
              </div>
              <div className="grid gap-px bg-line border border-line">
                {result.references.map((r, i) => (
                  <div
                    key={`${r.title}-${r.section_number}-${i}`}
                    className="p-4 bg-surface"
                  >
                    <div className="flex items-baseline gap-3 mb-1.5 flex-wrap">
                      <span className="font-semibold text-ink">{r.title}</span>
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
                    </div>
                    {r.excerpt && (
                      <blockquote className="text-sm text-ink-soft leading-relaxed">
                        {r.excerpt}
                      </blockquote>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {feedback === "negative" && !failureMode && (
            <div className="border-2 border-ink p-4 bg-surface">
              <div className="text-[11px] tracking-[0.25em] uppercase font-bold text-ink mb-3">
                מה השתבש?
              </div>
              <div className="flex flex-wrap gap-2">
                {(Object.keys(failureLabels) as FailureMode[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => tagFailure(m)}
                    className="px-3 py-1.5 text-sm border border-line-strong hover:border-ink hover:bg-line/40 transition"
                  >
                    {failureLabels[m]}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-ink-soft mt-3 leading-relaxed">
                "השליפה החטיאה" = החלקים הנכונים לא נמצאו. "הניסוח שגוי" =
                החלקים נמצאו אבל התשובה לא נכונה.
              </p>
            </div>
          )}

          {failureMode && (
            <div className="px-4 py-3 bg-surface border-r-4 border-accent text-sm text-ink">
              נרשם: {failureLabels[failureMode]}
            </div>
          )}

          {result.sources.length > 0 && (
            <details className="border border-line">
              <summary className="px-4 py-3 cursor-pointer hover:bg-line/40 text-[11px] tracking-[0.25em] uppercase font-bold text-ink-soft">
                קטעי טקסט שנשלפו ({result.sources.length})
              </summary>
              <div className="border-t border-line grid gap-px bg-line">
                {result.sources.map((s, i) => (
                  <details key={s.chunk_id} className="bg-surface">
                    <summary className="px-4 py-2.5 cursor-pointer hover:bg-line/40 text-sm flex items-baseline gap-3">
                      <span className="font-mono text-accent">[{i + 1}]</span>
                      <span className="text-ink">{s.document_filename}</span>
                      {s.section_path && (
                        <span className="text-ink-soft font-mono text-xs">
                          {s.section_path}
                        </span>
                      )}
                    </summary>
                    <div className="px-4 py-3 border-t border-line text-xs leading-relaxed whitespace-pre-wrap text-ink-soft">
                      {s.text}
                    </div>
                  </details>
                ))}
              </div>
            </details>
          )}

          {result.retrieval_debug && <DebugPanel debug={result.retrieval_debug} />}
        </div>
      )}
    </>
  );
}

// Stages match the backend's SearchPipelineStage. Each stage maps to a fixed
// bar position so real events from the server snap the bar to that point;
// within a stage the bar inches forward by time so it doesn't look frozen
// while we wait for the next event.
const THINKING_STAGES: {
  key: SearchPipelineStage;
  label: string;
  pct: number;        // bar % when this stage starts
  typicalMs: number;  // typical time spent in this stage
}[] = [
  { key: "analyzing",  label: "ניתוח השאלה",  pct: 0,  typicalMs: 800 },
  { key: "searching",  label: "חיפוש בארכיון", pct: 20, typicalMs: 1500 },
  { key: "ranking",    label: "דירוג מקורות",  pct: 45, typicalMs: 800 },
  { key: "generating", label: "ניסוח תשובה",   pct: 65, typicalMs: 8000 },
];
const FINAL_PCT = 95; // bar cap until real "done" event lands

function ThinkingProgress({
  stage,
  detail,
}: {
  stage: SearchPipelineStage | null;
  detail: string | null;
}) {
  // Tick so the bar inches forward within the active stage.
  const [tick, setTick] = useState(0);
  // Mark when each stage was entered so within-stage progress is computed
  // relative to that point in time, not from page load.
  const [stageEnteredAt, setStageEnteredAt] = useState<number>(() => Date.now());

  useEffect(() => {
    setStageEnteredAt(Date.now());
  }, [stage]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 150);
    return () => clearInterval(id);
  }, []);
  // touch tick so React doesn't warn it's unused; the value itself is irrelevant
  void tick;

  const stageIdx = THINKING_STAGES.findIndex((s) => s.key === stage);
  const currentIdx = stageIdx >= 0 ? stageIdx : 0;
  const current = THINKING_STAGES[currentIdx];
  const next = THINKING_STAGES[currentIdx + 1];
  const stageStartPct = current.pct;
  const stageEndPct = next ? next.pct : FINAL_PCT;

  // Time-based fill within this stage: ramp toward stageEndPct over typicalMs,
  // but ease so we approach (don't cross) the end. If the stage is slow, we
  // sit near the boundary; once the next stage event fires, we jump cleanly.
  const elapsedInStage = Date.now() - stageEnteredAt;
  const progressRatio = 1 - Math.exp(-elapsedInStage / current.typicalMs);
  const pct = stageStartPct + (stageEndPct - stageStartPct) * progressRatio;

  return (
    <section
      className="mb-8 py-5 border-y-2 border-ink animate-fade-up"
      role="status"
      aria-live="polite"
      aria-label="מתבצע חיפוש"
    >
      <div className="h-[3px] bg-line overflow-hidden mb-4">
        <div
          className="h-full bg-accent transition-[width] duration-300 ease-out"
          style={{ width: `${Math.min(pct, FINAL_PCT)}%` }}
        />
      </div>
      <div className="grid grid-cols-4 gap-2 text-[11px] tracking-wider uppercase font-bold">
        {THINKING_STAGES.map((s, i) => {
          const state =
            i < currentIdx ? "done" : i === currentIdx ? "active" : "pending";
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
      {detail && (
        <div className="mt-3 text-xs text-ink-soft">{detail}</div>
      )}
    </section>
  );
}

function RecentQuestions({ onPick }: { onPick: (q: string) => void }) {
  const [questions, setQuestions] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .recentQuestions(8)
      .then((qs) => {
        if (!cancelled) setQuestions(qs);
      })
      .catch(() => {
        if (!cancelled) setQuestions([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (questions === null || questions.length === 0) return null;

  return (
    <section className="mt-10 animate-fade-up">
      <div className="text-[11px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-4 flex items-center gap-3">
        <span>שאלות אחרונות</span>
        <span className="flex-1 h-px bg-line" />
      </div>
      <ul className="border border-line">
        {questions.map((q, i) => (
          <li
            key={q}
            className={i > 0 ? "border-t border-line" : ""}
          >
            <button
              type="button"
              onClick={() => onPick(q)}
              className="group w-full text-right px-4 py-3 hover:bg-line/40 transition flex items-baseline gap-4 text-sm text-ink"
            >
              <span className="font-mono text-xs text-ink-soft group-hover:text-accent transition w-6 shrink-0">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="flex-1">{q}</span>
              <span className="text-ink-soft group-hover:text-accent transition text-xs opacity-0 group-hover:opacity-100">
                ←
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
      title: "פירוק מסמכים",
      body: (
        <>
          כל תקנון מחולק אוטומטית לסעיפים, פרקים ונהלים — היחידה הקטנה
          ביותר של משמעות בשפה משפטית.
        </>
      ),
    },
    {
      title: "טביעת אצבע סמנטית",
      body: (
        <>
          מודל שפה מתרגם כל קטע לייצוג מספרי שלוכד את <em>המשמעות</em>, לא
          רק את המילים. שני קטעים שמדברים על אותו דבר במילים שונות יקבלו
          טביעות אצבע דומות.
        </>
      ),
    },
    {
      title: "התאמה לשאלה",
      body: (
        <>
          השאלה מתורגמת לטביעת אצבע משלה. המערכת מאתרת את הקטעים הקרובים
          אליה ביותר במשמעות, ובמקביל גם חיפוש מילולי לאיתור מספרי סעיפים
          ספציפיים. מנוע דירוג ייעודי מעלה את הרלוונטיים ביותר לראש.
        </>
      ),
    },
    {
      title: "ניסוח עם מקורות",
      body: (
        <>
          הקטעים הרלוונטיים נשלחים ל-Claude שמנסח תשובה תוך ציטוט המקור
          המדויק. אם אין מספיק עוגן במסמכים — המערכת תאמר שלא מצאה תשובה,
          ולא תמציא.
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
        זה לא חיפוש מילים כמו Ctrl+F — המערכת קוראת את התקנונים
        <strong className="text-ink"> לפי משמעות </strong>
        ומשתמשת ב-AI כדי לנסח תשובה מבוססת מקורות.
      </p>

      <ol className="grid md:grid-cols-2 gap-px bg-line border border-line">
        {steps.map((s, i) => (
          <li key={s.title} className="bg-surface p-5">
            <div className="flex items-baseline gap-3 mb-2">
              <span className="font-mono text-accent font-bold text-sm">
                0{i + 1}
              </span>
              <h3 className="font-display font-bold text-ink">{s.title}</h3>
            </div>
            <p className="text-sm text-ink-soft leading-relaxed">{s.body}</p>
          </li>
        ))}
      </ol>

      <div className="mt-4 pt-4 border-t border-line text-xs text-ink-soft leading-relaxed">
        <span className="text-ink font-semibold">זמן תגובה:</span> בדרך כלל 5–15
        שניות. המערכת קוראת, מבינה, ומחברת בין סעיפים בכל שאלה. סבלנות שווה
        תשובה איכותית.
      </div>
    </section>
  );
}
