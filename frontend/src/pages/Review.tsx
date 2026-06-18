import { useEffect, useState } from "react";
import { api, type QueryListItem } from "../lib/api";

export default function Review() {
  const [queries, setQueries] = useState<QueryListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "needs_review" | "feedback">("needs_review");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editNote, setEditNote] = useState("");
  const [busy, setBusy] = useState(false);

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
      <header className="mb-6">
        <h1 className="text-2xl font-bold">תור בדיקה</h1>
        <p className="text-ink-soft mt-1 text-sm">סקירת שאלות, סימון תשובות כסמכותיות, או דחייה.</p>
      </header>

      <div className="mb-4 flex gap-2 text-sm">
        {(["needs_review", "feedback", "all"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1 rounded ${
              filter === f ? "bg-accent text-white" : "bg-stone-100 hover:bg-stone-200"
            }`}
          >
            {f === "needs_review" ? "ממתינות לבדיקה" : f === "feedback" ? "עם משוב" : "הכול"}
          </button>
        ))}
        <button onClick={load} className="ml-auto px-3 py-1 rounded text-ink-soft hover:bg-stone-100">
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
              <div key={q.id} className="bg-white border border-stone-200 rounded-md p-5">
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
                        <span className="mr-2 text-emerald-600">👍</span>
                      )}
                      {q.feedback === "negative" && (
                        <span className="mr-2 text-red-600">👎</span>
                      )}
                      {q.reviewer_action && (
                        <span className="mr-2 inline-block bg-stone-200 px-2 py-0.5 rounded text-[10px]">
                          {q.reviewer_action === "approved"
                            ? "אושר"
                            : q.reviewer_action === "edited"
                            ? "ערוך + אושר"
                            : "נדחה"}
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
                      className="w-full px-3 py-2 border border-stone-300 rounded text-sm"
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
                      className="w-full px-3 py-2 border border-stone-300 rounded text-sm"
                    />
                  </div>
                )}

                {q.reviewer_action ? (
                  <div className="text-xs text-ink-soft italic">פעולה כבר נרשמה.</div>
                ) : (
                  <div className="flex gap-2 text-sm">
                    {isEditing ? (
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
                          className="px-3 py-1.5 bg-stone-100 hover:bg-stone-200 rounded"
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
                          className="px-3 py-1.5 bg-stone-100 hover:bg-stone-200 rounded"
                        >
                          ערוך + אשר
                        </button>
                        <button
                          onClick={() => reject(q)}
                          disabled={busy}
                          className="px-3 py-1.5 bg-red-50 text-red-900 border border-red-200 hover:bg-red-100 rounded mr-auto"
                        >
                          ✕ דחה
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
