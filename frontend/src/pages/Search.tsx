import { useState } from "react";
import { api, type FailureMode, type RetrievalDebugRow, type SearchResponse } from "../lib/api";

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

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setFeedback(null);
    setFailureMode(null);
    try {
      setResult(await api.search(question));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const submitFeedback = async (kind: "positive" | "negative") => {
    if (!result) return;
    setFeedback(kind);
    try {
      await api.feedback(result.query_id, kind);
    } catch (err) {
      setFeedback(null);
      setError(err instanceof Error ? err.message : String(err));
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
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="mt-3 px-6 py-2.5 bg-brand-gradient text-white font-semibold rounded-full shadow-soft hover:shadow-lift disabled:opacity-50 disabled:shadow-none transition"
        >
          {loading ? "מחפש..." : "שאל"}
        </button>
      </form>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-900 text-sm whitespace-pre-wrap">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-6 animate-fade-up">
          <div className={`p-5 border rounded-xl shadow-soft ${confidenceColors[result.confidence] || ""}`}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs tracking-wider uppercase font-bold">
                {confidenceLabel[result.confidence] || result.confidence}
              </div>
              {result.served_from === "hitl_cache" && (
                <span className="text-[10px] bg-accent text-white px-2 py-0.5 rounded-full">
                  מהמטמון
                </span>
              )}
            </div>
            <p className="text-lg leading-relaxed whitespace-pre-wrap">{result.answer}</p>

            {result.confidence !== "refused" && (
              <div className="mt-4 pt-4 border-t border-current/20 flex flex-wrap items-center gap-3">
                <span className="text-xs">האם התשובה מדויקת?</span>
                <button
                  onClick={() => submitFeedback("positive")}
                  disabled={feedback !== null}
                  className={`px-3 py-1 text-sm rounded-full transition ${
                    feedback === "positive"
                      ? "bg-emerald-600 text-white"
                      : "bg-white border border-current/30 hover:bg-emerald-100"
                  }`}
                >
                  👍 כן
                </button>
                <button
                  onClick={() => submitFeedback("negative")}
                  disabled={feedback !== null}
                  className={`px-3 py-1 text-sm rounded-full transition ${
                    feedback === "negative"
                      ? "bg-red-600 text-white"
                      : "bg-white border border-current/30 hover:bg-red-100"
                  }`}
                >
                  👎 לא
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
            <div>
              <div className="text-xs tracking-wider uppercase text-accent font-bold mb-3">
                מקורות
              </div>
              <div className="space-y-3">
                {result.sources.map((s, i) => (
                  <details
                    key={s.chunk_id}
                    className="bg-white border border-stone-200 rounded-xl overflow-hidden shadow-soft"
                  >
                    <summary className="px-4 py-3 cursor-pointer hover:bg-stone-50 text-sm">
                      <span className="font-semibold text-accent">[{i + 1}]</span>{" "}
                      <span className="text-ink">{s.document_filename}</span>
                      {s.section_path && (
                        <span className="text-ink-soft mr-2">⋅ {s.section_path}</span>
                      )}
                    </summary>
                    <div className="px-4 py-3 border-t border-stone-200 text-sm leading-relaxed whitespace-pre-wrap bg-stone-50">
                      {s.text}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}

          {result.retrieval_debug && <DebugPanel debug={result.retrieval_debug} />}
        </div>
      )}
    </>
  );
}
