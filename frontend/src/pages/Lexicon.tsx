import { useEffect, useState } from "react";
import { api, type LexiconItem, type LexiconSuggestion } from "../lib/api";

export default function Lexicon() {
  const [items, setItems] = useState<LexiconItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<LexiconSuggestion[] | null>(null);
  const [suggesting, setSuggesting] = useState(false);

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

  const generateSuggestions = async () => {
    setSuggesting(true);
    setError(null);
    try {
      setSuggestions(await api.suggestLexicon());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSuggesting(false);
    }
  };

  const acceptSuggestion = async (s: LexiconSuggestion) => {
    setBusy(true);
    try {
      await api.createLexicon({ term: s.term, expansion: s.expansion, notes: s.why });
      setSuggestions((cur) => (cur ? cur.filter((x) => x.term !== s.term) : cur));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="mb-10 flex items-end justify-between flex-wrap gap-3">
        <div>
          <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
            לקסיקון
          </div>
          <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
            מילון מונחים
          </h1>
          <p className="text-ink-soft mt-4 text-sm max-w-xl leading-relaxed">
            מונחים תחומיים שאלרום מסבירה ל-AI לפני שהוא עונה — כדי שמילים
            ייחודיות לקיבוץ לא תפורשנה לא נכון.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={generateSuggestions}
            disabled={suggesting}
            className="px-3 py-1.5 bg-white border border-line-strong hover:border-accent text-sm rounded-full text-ink-soft hover:text-accent transition disabled:opacity-50"
          >
            {suggesting ? "מנתח..." : "הצע מתוך שאלות שנכשלו"}
          </button>
          {editingId === null && (
            <button
              onClick={() => {
                setEditingId("new");
                setTerm("");
                setExpansion("");
                setNotes("");
              }}
              className="px-3 py-1.5 bg-accent text-white text-sm rounded-full"
            >
              + הוסף מונח
            </button>
          )}
        </div>
      </header>

      {suggestions !== null && (
        <div className="mb-6 p-4 bg-white border border-amber-300 ">
          <div className="text-xs font-bold text-amber-900 tracking-wide mb-3">
            הצעות מתוך {suggestions.length} שאלות שנכשלו לאחרונה
          </div>
          {suggestions.length === 0 ? (
            <div className="text-sm text-ink-soft">
              לא נמצאו מועמדים. אין שאלות שכשלו לאחרונה, או שכל המונחים שהוצעו כבר קיימים.
            </div>
          ) : (
            <div className="space-y-2">
              {suggestions.map((s) => (
                <div
                  key={s.term}
                  className="flex items-start justify-between gap-3 p-3 bg-amber-50 rounded-lg"
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-ink">{s.term}</div>
                    <div className="text-sm text-ink mt-1">{s.expansion}</div>
                    <div className="text-xs text-ink-soft mt-1 italic">
                      מתוך: "{s.source_question}"
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button
                      onClick={() => acceptSuggestion(s)}
                      disabled={busy}
                      className="text-xs px-2 py-1 bg-emerald-600 text-white hover:bg-emerald-700 rounded disabled:opacity-50"
                    >
                      קבל
                    </button>
                    <button
                      onClick={() =>
                        setSuggestions((cur) =>
                          cur ? cur.filter((x) => x.term !== s.term) : cur
                        )
                      }
                      className="text-xs px-2 py-1 text-ink-soft hover:bg-line rounded"
                    >
                      דחה
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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
                className="w-full px-3 py-2 border border-line-strong rounded text-sm"
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
                className="w-full px-3 py-2 border border-line-strong rounded text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                הערות פנימיות
              </label>
              <input
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="w-full px-3 py-2 border border-line-strong rounded text-sm"
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
                className="px-3 py-1.5 bg-line hover:bg-stone-200 rounded"
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
            <div key={it.id} className="bg-white border border-line rounded-md p-4">
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
