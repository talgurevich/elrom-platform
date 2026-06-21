import { useEffect, useState } from "react";
import { api, type AuthoritativeItem } from "../lib/api";

export default function Authoritative() {
  const [items, setItems] = useState<AuthoritativeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.listAuthoritative());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const retire = async (item: AuthoritativeItem) => {
    if (!confirm(`לבטל את התשובה "${item.canonical_question.slice(0, 50)}..."?`)) return;
    setBusy(true);
    try {
      await api.updateAuthoritative(item.id, { status: "retired" });
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
          ספרייה
        </div>
        <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
          תשובות מאושרות
        </h1>
        <p className="text-ink-soft mt-4 text-sm max-w-xl leading-relaxed">
          הספרייה שמייצרת את"המטמון" — שאלות עתידיות דומות יענו ישירות מכאן.
        </p>
      </header>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-900 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-ink-soft">טוען...</div>
      ) : items.length === 0 ? (
        <div className="text-ink-soft py-8 text-center">
          עדיין אין תשובות מאושרות. אשר תשובה מ"תור בדיקה" כדי להתחיל.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((it) => (
            <div key={it.id} className="bg-white border border-line rounded-md p-4">
              <div className="flex items-start gap-3 mb-2">
                <div className="flex-1">
                  <div className="font-semibold text-ink">{it.canonical_question}</div>
                  <div className="text-xs text-ink-soft mt-1">
                    {new Date(it.approved_at).toLocaleString("he-IL")} ⋅ סף דמיון:{" "}
                    {it.similarity_threshold.toFixed(2)}
                  </div>
                </div>
                <button
                  onClick={() => retire(it)}
                  disabled={busy}
                  className="text-xs px-2 py-1 text-red-700 hover:bg-red-50 rounded"
                >
                  בטל
                </button>
              </div>
              <div className="text-sm text-ink whitespace-pre-wrap leading-relaxed mt-2">
                {it.answer}
              </div>
              {it.internal_note && (
                <div className="text-xs text-ink-soft mt-2 italic">הערה: {it.internal_note}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
