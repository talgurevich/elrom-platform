import { useState } from "react";
import { api, type SearchResponse } from "../lib/api";

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

export default function Search() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<"positive" | "negative" | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setFeedback(null);
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

  return (
    <>
      <header className="mb-10">
        <h1 className="text-3xl font-bold">חיפוש בזיכרון הארגוני</h1>
        <p className="text-ink-soft mt-2">שאל שאלה בעברית. קבל תשובה מבוססת מקורות.</p>
      </header>

      <form onSubmit={submit} className="mb-8">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="לדוגמה: מה הוחלט בעניין קדימות לקומה שנייה?"
          rows={3}
          className="w-full px-4 py-3 border border-stone-300 rounded-md focus:border-accent focus:ring-2 focus:ring-accent/20 outline-none text-base"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="mt-3 px-6 py-2 bg-accent text-white font-semibold rounded-md disabled:opacity-50"
        >
          {loading ? "מחפש..." : "שאל"}
        </button>
      </form>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-md text-red-900 text-sm whitespace-pre-wrap">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <div className={`p-5 border rounded-md ${confidenceColors[result.confidence] || ""}`}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs tracking-wider uppercase font-bold">
                {confidenceLabel[result.confidence] || result.confidence}
              </div>
              {result.served_from === "hitl_cache" && (
                <span className="text-[10px] bg-accent text-white px-2 py-0.5 rounded">מהמטמון</span>
              )}
            </div>
            <p className="text-lg leading-relaxed whitespace-pre-wrap">{result.answer}</p>

            {result.confidence !== "refused" && (
              <div className="mt-4 pt-4 border-t border-current/20 flex items-center gap-3">
                <span className="text-xs">האם התשובה מדויקת?</span>
                <button
                  onClick={() => submitFeedback("positive")}
                  disabled={feedback !== null}
                  className={`px-3 py-1 text-sm rounded ${
                    feedback === "positive" ? "bg-emerald-600 text-white" : "bg-white border border-current/30 hover:bg-emerald-100"
                  }`}
                >
                  👍 כן
                </button>
                <button
                  onClick={() => submitFeedback("negative")}
                  disabled={feedback !== null}
                  className={`px-3 py-1 text-sm rounded ${
                    feedback === "negative" ? "bg-red-600 text-white" : "bg-white border border-current/30 hover:bg-red-100"
                  }`}
                >
                  👎 לא
                </button>
              </div>
            )}
          </div>

          {result.sources.length > 0 && (
            <div>
              <div className="text-xs tracking-wider uppercase text-accent font-bold mb-3">מקורות</div>
              <div className="space-y-3">
                {result.sources.map((s, i) => (
                  <details
                    key={s.chunk_id}
                    className="bg-white border border-stone-200 rounded-md overflow-hidden"
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
        </div>
      )}
    </>
  );
}
