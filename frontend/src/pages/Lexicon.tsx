import { useEffect, useState } from "react";
import { api, type LexiconItem } from "../lib/api";

export default function Lexicon() {
  const [items, setItems] = useState<LexiconItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [editingId, setEditingId] = useState<string | "new" | null>(null);
  const [term, setTerm] = useState("");
  const [expansion, setExpansion] = useState("");
  const [notes, setNotes] = useState("");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.listLexicon());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const startEdit = (item: LexiconItem) => {
    setEditingId(item.id);
    setTerm(item.term);
    setExpansion(item.expansion);
    setNotes(item.notes || "");
  };

  const cancel = () => {
    setEditingId(null);
    setTerm("");
    setExpansion("");
    setNotes("");
  };

  const save = async () => {
    if (!term.trim() || !expansion.trim()) return;
    setBusy(true);
    try {
      if (editingId === "new") {
        await api.createLexicon({ term, expansion, notes: notes || undefined });
      } else if (editingId) {
        await api.updateLexicon(editingId, { term, expansion, notes });
      }
      cancel();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item: LexiconItem) => {
    if (!confirm(`למחוק את המונח "${item.term}"?`)) return;
    setBusy(true);
    try {
      await api.deleteLexicon(item.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold">מילון מונחים</h1>
          <p className="text-ink-soft mt-1 text-sm">
            מונחים תחומיים שאלרום מסבירה ל-AI לפני שהוא עונה.
          </p>
        </div>
        {editingId === null && (
          <button
            onClick={() => {
              setEditingId("new");
              setTerm("");
              setExpansion("");
              setNotes("");
            }}
            className="px-3 py-1.5 bg-accent text-white text-sm rounded"
          >
            + הוסף מונח
          </button>
        )}
      </header>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-900 text-sm">
          {error}
        </div>
      )}

      {editingId && (
        <div className="mb-6 p-4 bg-white border border-accent/30 rounded-md">
          <div className="grid gap-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                מונח
              </label>
              <input
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder='למשל: "השינוי"'
                className="w-full px-3 py-2 border border-stone-300 rounded text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                הסבר (יוטמע ב-prompt ל-AI)
              </label>
              <textarea
                value={expansion}
                onChange={(e) => setExpansion(e.target.value)}
                rows={3}
                placeholder="למשל: המעבר מקיבוץ שיתופי לקיבוץ מתחדש..."
                className="w-full px-3 py-2 border border-stone-300 rounded text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                הערות פנימיות
              </label>
              <input
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="w-full px-3 py-2 border border-stone-300 rounded text-sm"
              />
            </div>
            <div className="flex gap-2 text-sm">
              <button
                onClick={save}
                disabled={busy || !term.trim() || !expansion.trim()}
                className="px-3 py-1.5 bg-accent text-white rounded disabled:opacity-50"
              >
                שמור
              </button>
              <button
                onClick={cancel}
                className="px-3 py-1.5 bg-stone-100 hover:bg-stone-200 rounded"
              >
                ביטול
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-ink-soft">טוען...</div>
      ) : items.length === 0 && editingId !== "new" ? (
        <div className="text-ink-soft py-8 text-center">המילון ריק. הוסף מונח ראשון.</div>
      ) : (
        <div className="space-y-2">
          {items.map((it) => (
            <div key={it.id} className="bg-white border border-stone-200 rounded-md p-4">
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <div className="font-semibold text-ink">{it.term}</div>
                  <div className="text-sm text-ink mt-1 whitespace-pre-wrap">{it.expansion}</div>
                  {it.notes && <div className="text-xs text-ink-soft mt-2 italic">{it.notes}</div>}
                </div>
                <div className="flex flex-col gap-1">
                  <button
                    onClick={() => startEdit(it)}
                    className="text-xs px-2 py-1 text-accent hover:bg-accent/10 rounded"
                  >
                    ערוך
                  </button>
                  <button
                    onClick={() => remove(it)}
                    disabled={busy}
                    className="text-xs px-2 py-1 text-red-700 hover:bg-red-50 rounded"
                  >
                    מחק
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
