import { useEffect, useState } from "react";
import {
  api,
  type FailureMode,
  type RetrievalDebugRow,
  type SearchPipelineStage,
  type SearchResponse,
} from "../lib/api";

const confidenceColors: Record<string, string> = {
  confident: "bg-emerald-50 text-emerald-900 border-emerald-200",
  uncertain: "bg-amber-50 text-amber-900 border-amber-200",
  refused: "bg-stone-100 text-stone-700 border-stone-300",
};

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
        <h1 className="font-display text-4xl font-bold tracking-tight">
          חיפוש בזיכרון הארגוני
        </h1>
        <p className="text-ink-soft mt-3 text-base">
          שאל שאלה בעברית. קבל תשובה מבוססת מקורות.
        </p>
      </header>

      <form onSubmit={submit} className="mb-8">
        <div className="relative">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="לדוגמה: מה הוחלט בעניין קדימות לקומה שנייה?"
            rows={3}
            className="w-full px-4 py-3 bg-white border border-stone-300 rounded-xl shadow-soft focus:border-accent focus:ring-4 focus:ring-accent/15 outline-none text-base resize-none transition"
          />
        </div>
        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="px-6 py-2.5 bg-brand-gradient text-white font-semibold rounded-full shadow-soft hover:shadow-lift disabled:opacity-50 disabled:shadow-none transition min-w-[110px]"
          >
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <span className="inline-block w-3 h-3 rounded-full bg-white/80 animate-pulse" />
                <span>חושב</span>
              </span>
            ) : (
              "שאל"
            )}
          </button>
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
            <div className="p-4 border border-amber-300 bg-amber-50 rounded-xl shadow-soft">
              <div className="text-xs font-bold text-amber-900 tracking-wide mb-2 flex items-center gap-2">
                <span>⚡</span>
                <span>קיימת תשובה מאושרת קרובה בארכיון</span>
              </div>
              <div className="space-y-2">
                {result.near_misses.map((nm) => (
                  <details
                    key={nm.authoritative_answer_id}
                    className="bg-white border border-amber-200 rounded-lg"
                  >
                    <summary className="px-3 py-2 cursor-pointer text-sm">
                      <span className="text-amber-900 font-semibold">
                        {Math.round(nm.similarity * 100)}% דמיון:
                      </span>{" "}
                      <span className="text-ink">{nm.canonical_question}</span>
                    </summary>
                    <div className="px-3 py-2 border-t border-amber-200 text-sm leading-relaxed whitespace-pre-wrap text-ink-soft">
                      {nm.answer}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}
          {/* 0. Retry banner (one-shot notice after auto-retry from 👎 on cached answer) */}
          {justRetried && (
            <div className="px-4 py-2 rounded-lg bg-emerald-50 border border-emerald-200 text-sm text-emerald-900">
              ✓ התשובה הקודמת הוסרה מהמטמון. הנה ניסיון חדש מבוסס מקורות.
            </div>
          )}

          {/* 1. Confidence header */}
          <div
            className={`inline-flex items-center gap-3 px-4 py-2 rounded-full border ${
              confidenceColors[result.confidence] || ""
            }`}
          >
            <span className="text-xs tracking-wider uppercase font-bold">
              {confidenceLabel[result.confidence] || result.confidence}
            </span>
            {result.served_from === "hitl_cache" && (
              <span className="text-[10px] bg-accent text-white px-2 py-0.5 rounded-full">
                מהמטמון
              </span>
            )}
          </div>

          {/* 2. Cited clauses */}
          {result.references && result.references.length > 0 && (
            <div>
              <div className="text-xs tracking-wider uppercase text-accent font-bold mb-3">
                סימוכין
              </div>
              <div className="space-y-2">
                {result.references.map((r, i) => (
                  <div
                    key={`${r.title}-${r.section_number}-${i}`}
                    className="p-4 bg-white border border-stone-200 rounded-xl shadow-soft"
                  >
                    <div className="flex items-baseline gap-2 mb-1 flex-wrap">
                      <span className="font-semibold text-accent">{r.title}</span>
                      {r.section_number && (
                        <span className="text-sm text-ink font-mono">
                          סעיף {r.section_number}
                        </span>
                      )}
                      {r.source_type && (
                        <span className="text-[10px] tracking-widest uppercase text-ink-soft mr-auto">
                          {r.source_type}
                        </span>
                      )}
                    </div>
                    {r.excerpt && (
                      <blockquote className="text-sm text-ink-soft leading-relaxed border-r-2 border-accent/30 pr-3 italic">
                        "{r.excerpt}"
                      </blockquote>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 3. Natural-language answer */}
          <div className="p-5 bg-white border border-stone-200 rounded-xl shadow-soft">
            <div className="text-xs tracking-wider uppercase text-ink-soft font-bold mb-2">
              תשובה
            </div>
            <p className="text-lg leading-relaxed whitespace-pre-wrap text-ink">
              {result.answer}
            </p>

            {result.confidence !== "refused" && (
              <div className="mt-4 pt-4 border-t border-stone-200 flex flex-wrap items-center gap-3">
                <span className="text-xs text-ink-soft">
                  {retrying ? "מחפש שוב…" : "האם התשובה מדויקת?"}
                </span>
                <button
                  onClick={() => submitFeedback("positive")}
                  disabled={feedback !== null || retrying}
                  className={`px-3 py-1 text-sm rounded-full transition ${
                    feedback === "positive"
                      ? "bg-emerald-600 text-white"
                      : "bg-white border border-stone-300 hover:bg-emerald-50"
                  }`}
                >
                  👍 כן
                </button>
                <button
                  onClick={() => submitFeedback("negative")}
                  disabled={feedback !== null || retrying}
                  className={`px-3 py-1 text-sm rounded-full transition ${
                    feedback === "negative"
                      ? "bg-red-600 text-white"
                      : "bg-white border border-stone-300 hover:bg-red-50"
                  }`}
                >
                  👎 לא
                </button>
                <button
                  onClick={promoteToGolden}
                  disabled={promoting || promoted}
                  className="px-3 py-1 text-sm rounded-full bg-white border border-stone-300 hover:bg-stone-100 disabled:opacity-60 text-ink-soft"
                  title="הפוך לשאלת זהב להרצה חוזרת"
                >
                  {promoted ? "✓ נשמר כזהב" : promoting ? "..." : "⭐ קבע כשאלת זהב"}
                </button>
              </div>
            )}
          </div>

          {feedback === "negative" && !failureMode && (
            <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl">
              <div className="text-xs font-bold text-amber-900 mb-2 tracking-wide">
                מה השתבש?
              </div>
              <div className="flex flex-wrap gap-2">
                {(Object.keys(failureLabels) as FailureMode[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => tagFailure(m)}
                    className="px-3 py-1.5 text-sm bg-white border border-amber-300 hover:bg-amber-100 rounded-full transition"
                  >
                    {failureLabels[m]}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-amber-800 mt-2 leading-relaxed">
                "השליפה החטיאה" = החלקים הנכונים לא נמצאו. "הניסוח שגוי" = החלקים נמצאו אבל
                התשובה לא נכונה.
              </p>
            </div>
          )}

          {failureMode && (
            <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-900 text-sm">
              ✓ נרשם: {failureLabels[failureMode]}
            </div>
          )}

          {result.sources.length > 0 && (
            <details className="bg-white border border-stone-200 rounded-xl overflow-hidden shadow-soft">
              <summary className="px-4 py-3 cursor-pointer hover:bg-stone-50 text-sm font-semibold text-ink-soft">
                קטעי טקסט שנשלפו ({result.sources.length})
              </summary>
              <div className="px-4 py-3 border-t border-stone-200 space-y-3 bg-stone-50/50">
                {result.sources.map((s, i) => (
                  <details
                    key={s.chunk_id}
                    className="bg-white border border-stone-200 rounded-lg overflow-hidden"
                  >
                    <summary className="px-3 py-2 cursor-pointer hover:bg-stone-50 text-sm">
                      <span className="font-semibold text-accent">[{i + 1}]</span>{" "}
                      <span className="text-ink">{s.document_filename}</span>
                      {s.section_path && (
                        <span className="text-ink-soft mr-2">⋅ {s.section_path}</span>
                      )}
                    </summary>
                    <div className="px-3 py-2 border-t border-stone-200 text-xs leading-relaxed whitespace-pre-wrap bg-stone-50">
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
      className="mb-6 p-5 bg-white border border-stone-200 rounded-2xl shadow-soft animate-fade-up"
      role="status"
      aria-live="polite"
      aria-label="מתבצע חיפוש"
    >
      <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden mb-4">
        <div
          className="h-full bg-brand-gradient transition-[width] duration-300 ease-out"
          style={{ width: `${Math.min(pct, FINAL_PCT)}%` }}
        />
      </div>
      <div className="grid grid-cols-4 gap-2 text-xs text-center">
        {THINKING_STAGES.map((s, i) => {
          const state =
            i < currentIdx ? "done" : i === currentIdx ? "active" : "pending";
          const cls =
            state === "active"
              ? "text-accent font-semibold"
              : state === "done"
              ? "text-ink-soft"
              : "text-stone-300";
          return (
            <span key={s.key} className={cls}>
              {s.label}
            </span>
          );
        })}
      </div>
      {detail && (
        <div className="mt-3 text-xs text-ink-soft text-center">{detail}</div>
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
    <section className="mt-6 p-6 bg-white border border-stone-200 rounded-2xl shadow-soft animate-fade-up">
      <div className="text-xs tracking-wider uppercase text-accent font-bold mb-3">
        שאלות אחרונות
      </div>
      <p className="text-xs text-ink-soft mb-4 leading-relaxed">
        שאלות שנשאלו לאחרונה במאגר הזה. לחץ על אחת כדי לשאול שוב.
      </p>
      <ul className="space-y-1.5">
        {questions.map((q) => (
          <li key={q}>
            <button
              type="button"
              onClick={() => onPick(q)}
              className="group w-full text-right px-3 py-2 rounded-lg border border-stone-200 bg-stone-50 hover:bg-accent/5 hover:border-accent/40 transition text-sm text-ink"
            >
              <span className="text-ink-soft text-xs mr-2 group-hover:text-accent transition">
                ›
              </span>
              {q}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function HowItWorks() {
  return (
    <section className="mt-2 mb-6 p-6 bg-white border border-stone-200 rounded-2xl shadow-soft animate-fade-up">
      <div className="text-xs tracking-wider uppercase text-accent font-bold mb-3">
        איך זה עובד?
      </div>
      <p className="text-sm text-ink-soft leading-relaxed mb-5">
        זה לא חיפוש מילים כמו Ctrl+F — המערכת קוראת את התקנונים
        <strong className="text-ink"> לפי משמעות </strong>
        ומשתמשת ב-AI כדי לנסח תשובה מבוססת מקורות. הנה התהליך:
      </p>

      <ol className="space-y-3 text-sm leading-relaxed">
        <li className="flex gap-3">
          <span className="shrink-0 w-7 h-7 rounded-full bg-accent/10 text-accent font-bold flex items-center justify-center text-xs">
            1
          </span>
          <span className="text-ink">
            <strong>פירוק מסמכים לקטעים.</strong> כל תקנון מחולק אוטומטית
            לסעיפים, פרקים, ונהלים — היחידה הקטנה ביותר של משמעות בשפה
            משפטית.
          </span>
        </li>
        <li className="flex gap-3">
          <span className="shrink-0 w-7 h-7 rounded-full bg-accent/10 text-accent font-bold flex items-center justify-center text-xs">
            2
          </span>
          <span className="text-ink">
            <strong>טביעת אצבע סמנטית לכל קטע.</strong> מודל שפה מתרגם כל קטע
            לייצוג מספרי שלוכד את <em>המשמעות</em>, לא רק את המילים. שני קטעים
            שמדברים על אותו דבר במילים שונות יקבלו טביעות אצבע דומות.
          </span>
        </li>
        <li className="flex gap-3">
          <span className="shrink-0 w-7 h-7 rounded-full bg-accent/10 text-accent font-bold flex items-center justify-center text-xs">
            3
          </span>
          <span className="text-ink">
            <strong>השאלה שלך עוברת את אותו תהליך.</strong> השאלה מתורגמת
            לטביעת אצבע משלה והמערכת מאתרת את הקטעים הקרובים אליה ביותר
            במשמעות. במקביל רץ גם חיפוש מילולי לאיתור שמות ומספרי סעיפים
            ספציפיים. שני הזרמים מתמזגים, ומדורג מחדש מנוע ייעודי שמעלה את
            הרלוונטיים ביותר לראש.
          </span>
        </li>
        <li className="flex gap-3">
          <span className="shrink-0 w-7 h-7 rounded-full bg-accent/10 text-accent font-bold flex items-center justify-center text-xs">
            4
          </span>
          <span className="text-ink">
            <strong>תשובה בעברית מבוססת מקורות.</strong> הקטעים הרלוונטיים
            נשלחים ל-Claude שמנסח תשובה תוך ציטוט המקור המדויק. אם אין מספיק
            עוגן במסמכים — המערכת תאמר שלא מצאה תשובה, ולא תמציא.
          </span>
        </li>
      </ol>

      <div className="mt-5 pt-4 border-t border-stone-200 text-xs text-ink-soft leading-relaxed">
        <strong className="text-ink">זמן תגובה:</strong> בדרך כלל 5–15 שניות.
        זה לא Google — המערכת קוראת, מבינה, ומחברת בין סעיפים בכל שאלה.
        סבלנות שווה תשובה איכותית.
      </div>
    </section>
  );
}
