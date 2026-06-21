import { useEffect, useState } from "react";
import { api, type QueryListItem, type SearchResponse } from "../lib/api";

export default function Review() {
  const [queries, setQueries] = useState<QueryListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "needs_review" | "feedback">("needs_review");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editNote, setEditNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [retries, setRetries] = useState<Record<string, SearchResponse>>({});
  const [retrying, setRetrying] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = filter === "needs_review" ? { needs_review: true } : filter === "feedback" ? { feedback_only: true } : {};
      setQueries(await api.listQueries(params));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [filter]);

  const approve = async (q: QueryListItem, edited: boolean) => {
    setBusy(true);
    try {
      await api.approve(q.id, {
        edited_answer: edited ? editText : undefined,
        internal_note: editNote || undefined,
      });
      setEditingId(null);
      setEditText("");
      setEditNote("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const retry = async (q: QueryListItem) => {
    setRetrying(q.id);
    setError(null);
    try {
      const result = await api.search(q.question);
      setRetries((cur) => ({ ...cur, [q.id]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRetrying(null);
    }
  };

  const reject = async (q: QueryListItem) => {
    setBusy(true);
    try {
      await api.reject(q.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="mb-10">
        <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
          ביקורת
        </div>
        <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
          תור בדיקה
        </h1>
        <p className="text-ink-soft mt-4 text-sm max-w-xl leading-relaxed">
          סקירת שאלות שנשאלו, סימון תשובות כסמכותיות, או מחיקה.
        </p>
      </header>

      <div className="mb-4 flex gap-2 text-sm">
        {(["needs_review", "feedback", "all"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1 rounded ${
              filter === f ? "bg-ink text-surface" : "bg-line hover:bg-line-strong"
            }`}
          >
            {f === "needs_review" ? "ממתינות לבדיקה" : f === "feedback" ? "עם משוב" : "הכול"}
          </button>
        ))}
        <button onClick={load} className="ml-auto px-3 py-1 rounded text-ink-soft hover:bg-line">
          רענן
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-900 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-ink-soft">טוען...</div>
      ) : queries.length === 0 ? (
        <div className="text-ink-soft py-8 text-center">אין שאלות להציג.</div>
      ) : (
        <div className="space-y-4">
          {queries.map((q) => {
            const isEditing = editingId === q.id;
            return (
              <div key={q.id} className="bg-white border border-line rounded-md p-5">
                <div className="flex items-start gap-2 mb-3">
                  <div className="flex-1">
                    <div className="text-xs text-ink-soft mb-1">
                      {new Date(q.created_at).toLocaleString("he-IL")}
                      {q.served_from_cache && (
                        <span className="mr-2 inline-block bg-accent/10 text-accent px-2 py-0.5 rounded text-[10px]">
                          מהמטמון
                        </span>
                      )}
                      {q.feedback === "positive" && (
                        <span className="mr-2 inline-block border border-emerald-600 text-emerald-700 px-2 py-0.5 text-[10px] tracking-wider uppercase font-bold">
                          חיובי
                        </span>
                      )}
                      {q.feedback === "negative" && (
                        <span className="mr-2 inline-block border border-accent text-accent px-2 py-0.5 text-[10px] tracking-wider uppercase font-bold">
                          שלילי
                        </span>
                      )}
                      {q.reviewer_action && (
                        <span className="mr-2 inline-block bg-line border border-line-strong px-2 py-0.5 text-[10px] tracking-wider uppercase font-bold">
                          {q.reviewer_action === "approved"
                            ? "אושר"
                            : q.reviewer_action === "edited"
                            ? "ערוך + אושר"
                            : "נמחק"}
                        </span>
                      )}
                    </div>
                    <div className="font-semibold text-ink">{q.question}</div>
                  </div>
                </div>

                <div className="mb-3">
                  <div className="text-[10px] uppercase tracking-wider text-ink-soft mb-1">תשובה</div>
                  {isEditing ? (
                    <textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={4}
                      className="w-full px-3 py-2 border border-line-strong rounded text-sm"
                    />
                  ) : (
                    <div className="text-ink whitespace-pre-wrap text-sm leading-relaxed">
                      {q.answer || "—"}
                    </div>
                  )}
                </div>

                {isEditing && (
                  <div className="mb-3">
                    <div className="text-[10px] uppercase tracking-wider text-ink-soft mb-1">
                      הערה פנימית (אופציונלי)
                    </div>
                    <input
                      value={editNote}
                      onChange={(e) => setEditNote(e.target.value)}
                      placeholder="למה אישרת? לאיזה הקשר זה תקף?"
                      className="w-full px-3 py-2 border border-line-strong rounded text-sm"
                    />
                  </div>
                )}

                {retries[q.id] && (
                  <div className="mt-3 mb-4 p-4 bg-sky-50 border border-sky-200 rounded-lg">
                    <div className="text-[10px] uppercase tracking-wider text-sky-900 font-bold mb-2 flex items-center gap-2">
                      <span>🔁 תשובה חדשה</span>
                      <span className="text-sky-700 font-mono">
                        {retries[q.id].confidence}
                      </span>
                    </div>
                    <div className="text-ink text-sm whitespace-pre-wrap leading-relaxed mb-3">
                      {retries[q.id].answer}
                    </div>
                    {retries[q.id].references && retries[q.id].references.length > 0 && (
                      <div className="space-y-1">
                        {retries[q.id].references.map((r, i) => (
                          <div
                            key={`${q.id}-r-${i}`}
                            className="text-[11px] text-ink-soft"
                          >
                            <span className="font-semibold text-sky-900">{r.title}</span>
                            {r.section_number && (
                              <span className="font-mono"> · סעיף {r.section_number}</span>
                            )}
                            {r.excerpt && (
                              <span className="block italic mt-0.5 pr-3 border-r-2 border-sky-300">
                                "{r.excerpt}"
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="flex gap-2 text-sm flex-wrap">
                  <button
                    onClick={() => retry(q)}
                    disabled={retrying === q.id}
                    className="px-3 py-1.5 bg-sky-50 text-sky-900 border border-sky-200 hover:bg-sky-100 rounded disabled:opacity-50"
                    title="הרץ את השאלה שוב מול המערכת העדכנית"
                  >
                    {retrying === q.id ? "מריץ..." : retries[q.id] ? "🔁 הרץ שוב" : "🔁 הרץ שוב"}
                  </button>

                  {q.reviewer_action ? (
                    <div className="text-xs text-ink-soft italic self-center">
                      פעולה כבר נרשמה.
                    </div>
                  ) : isEditing ? (
                    <>
                      <button
                        onClick={() => approve(q, true)}
                        disabled={busy || !editText.trim()}
                        className="px-3 py-1.5 bg-accent text-white rounded disabled:opacity-50"
                      >
                        ערוך + אשר
                      </button>
                      <button
                        onClick={() => {
                          setEditingId(null);
                          setEditText("");
                          setEditNote("");
                        }}
                        className="px-3 py-1.5 bg-line hover:bg-stone-200 rounded"
                      >
                        ביטול
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => approve(q, false)}
                        disabled={busy || !q.answer}
                        className="px-3 py-1.5 bg-emerald-600 text-white rounded disabled:opacity-50"
                      >
                        ✓ אשר
                      </button>
                      <button
                        onClick={() => {
                          setEditingId(q.id);
                          setEditText(q.answer || "");
                        }}
                        disabled={busy}
                        className="px-3 py-1.5 bg-line hover:bg-stone-200 rounded"
                      >
                        ערוך + אשר
                      </button>
                      <button
                        onClick={() => reject(q)}
                        disabled={busy}
                        className="px-3 py-1.5 border border-line-strong hover:border-accent hover:text-accent text-ink-soft mr-auto"
                      >
                        מחק
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
