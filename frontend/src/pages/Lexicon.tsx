import { useEffect, useState } from "react";
import {
  api,
  type LexiconEntryType,
  type LexiconItem,
  type LexiconSuggestion,
} from "../lib/api";

type EditorState = {
  id: string | "new";
  term: string;
  surfaceForms: string[];
  entryType: LexiconEntryType;
  shortGloss: string;
  answererExpansion: string;
  notes: string;
};

const ENTRY_TYPE_LABELS: Record<LexiconEntryType, string> = {
  definition: "הגדרה",
  pointer: "הפניה",
  rule: "כלל",
};

const emptyEditor = (id: string | "new" = "new"): EditorState => ({
  id,
  term: "",
  surfaceForms: [],
  entryType: "definition",
  shortGloss: "",
  answererExpansion: "",
  notes: "",
});

function editorFromItem(item: LexiconItem): EditorState {
  return {
    id: item.id,
    term: item.term,
    surfaceForms: item.surface_forms || [],
    entryType: item.entry_type,
    shortGloss: item.short_gloss || "",
    answererExpansion: item.answerer_expansion || item.expansion || "",
    notes: item.notes || "",
  };
}

function formatRelativeDate(iso: string | null): string {
  if (!iso) return "לא הופעל";
  const then = new Date(iso).getTime();
  const days = Math.floor((Date.now() - then) / (1000 * 60 * 60 * 24));
  if (days <= 0) return "היום";
  if (days === 1) return "אתמול";
  if (days < 30) return `לפני ${days} ימים`;
  return `לפני ${Math.floor(days / 30)} חודשים`;
}

function SurfaceFormsEditor({
  forms,
  onChange,
}: {
  forms: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (forms.includes(trimmed)) {
      setDraft("");
      return;
    }
    onChange([...forms, trimmed]);
    setDraft("");
  };
  const removeAt = (i: number) => {
    onChange(forms.filter((_, idx) => idx !== i));
  };
  return (
    <div>
      <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
        צורות שטח ({forms.length}) — כל וריאציה תיתפס במטצ'ר
      </label>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {forms.map((f, i) => (
          <span
            key={`${f}-${i}`}
            className="inline-flex items-center gap-1 px-2 py-0.5 bg-stone-100 border border-line-strong rounded-full text-xs"
          >
            <span className={i === 0 ? "font-bold" : ""}>{f}</span>
            <button
              type="button"
              onClick={() => removeAt(i)}
              className="text-ink-soft hover:text-red-700"
              aria-label="הסר צורה"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="צורה נוספת (למשל: השיוכים)"
          className="flex-1 px-3 py-1.5 border border-line-strong rounded text-sm"
        />
        <button
          type="button"
          onClick={add}
          disabled={!draft.trim()}
          className="px-3 py-1.5 bg-stone-100 border border-line-strong rounded text-sm disabled:opacity-50"
        >
          הוסף
        </button>
      </div>
    </div>
  );
}

export default function Lexicon() {
  const [items, setItems] = useState<LexiconItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<LexiconSuggestion[] | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);

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

  const cancel = () => setEditor(null);

  const save = async () => {
    if (!editor) return;
    const term = editor.term.trim();
    const answererExpansion = editor.answererExpansion.trim();
    const shortGloss = editor.shortGloss.trim();
    if (!term) return;
    if (!answererExpansion && !shortGloss) return;
    setBusy(true);
    try {
      const payload = {
        term,
        surface_forms: editor.surfaceForms.length ? editor.surfaceForms : undefined,
        entry_type: editor.entryType,
        short_gloss: shortGloss,
        answerer_expansion: answererExpansion,
        notes: editor.notes || undefined,
      };
      if (editor.id === "new") {
        await api.createLexicon(payload);
      } else {
        await api.updateLexicon(editor.id, payload);
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
      await api.createLexicon({
        term: s.term,
        answerer_expansion: s.expansion,
        short_gloss: s.expansion.split(/[.!?]/)[0] || s.expansion,
        notes: s.why,
      });
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
            מונחים תחומיים שהארגון מסביר ל-AI לפני שהוא עונה — כדי שמילים
            ייחודיות לא תפורשנה לא נכון. כל מונח נמדד לפי מספר הפעמים שהופעל
            ב-30 הימים האחרונים כדי לזהות רשומות מתות.
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
          {editor === null && (
            <button
              onClick={() => setEditor(emptyEditor())}
              className="px-3 py-1.5 bg-accent text-white text-sm rounded-full"
            >
              + הוסף מונח
            </button>
          )}
        </div>
      </header>

      {suggestions !== null && (
        <div className="mb-6 p-4 bg-white border border-amber-300">
          <div className="text-xs font-bold text-amber-900 tracking-wide mb-3">
            הצעות מתוך {suggestions.length} שאלות שנכשלו לאחרונה
          </div>
          {suggestions.length === 0 ? (
            <div className="text-sm text-ink-soft">
              לא נמצאו מועמדים חדשים. יש גם קציר אוטומטי לילי מציטוטים ומראשי תיבות
              בתשובות — הרשומות המוצעות יופיעו כרשומות "נלמד · ממתין" למטה.
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
                          cur ? cur.filter((x) => x.term !== s.term) : cur,
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

      {editor && (
        <div className="mb-6 p-4 bg-white border border-accent/30 rounded-md">
          <div className="grid gap-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="md:col-span-2">
                <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                  מונח קנוני
                </label>
                <input
                  value={editor.term}
                  onChange={(e) =>
                    setEditor({ ...editor, term: e.target.value })
                  }
                  placeholder='למשל: "שיוך"'
                  className="w-full px-3 py-2 border border-line-strong rounded text-sm"
                />
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                  סוג רשומה
                </label>
                <select
                  value={editor.entryType}
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      entryType: e.target.value as LexiconEntryType,
                    })
                  }
                  className="w-full px-3 py-2 border border-line-strong rounded text-sm bg-white"
                >
                  {(Object.keys(ENTRY_TYPE_LABELS) as LexiconEntryType[]).map(
                    (k) => (
                      <option key={k} value={k}>
                        {ENTRY_TYPE_LABELS[k]}
                      </option>
                    ),
                  )}
                </select>
              </div>
            </div>
            <SurfaceFormsEditor
              forms={editor.surfaceForms}
              onChange={(next) => setEditor({ ...editor, surfaceForms: next })}
            />
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                הסבר קצר (לתצוגה על ריחוף בתשובה)
              </label>
              <input
                value={editor.shortGloss}
                onChange={(e) =>
                  setEditor({ ...editor, shortGloss: e.target.value })
                }
                placeholder="משפט אחד קצר להסבר על ריחוף"
                className="w-full px-3 py-2 border border-line-strong rounded text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                הרחבה למענה (יוטמע ב-prompt ל-AI)
              </label>
              <textarea
                value={editor.answererExpansion}
                onChange={(e) =>
                  setEditor({ ...editor, answererExpansion: e.target.value })
                }
                rows={3}
                placeholder="למשל: המעבר מקיבוץ שיתופי לקיבוץ מתחדש; ראה תקנון שיוך פירות נכסים..."
                className="w-full px-3 py-2 border border-line-strong rounded text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                הערות פנימיות
              </label>
              <input
                value={editor.notes}
                onChange={(e) =>
                  setEditor({ ...editor, notes: e.target.value })
                }
                className="w-full px-3 py-2 border border-line-strong rounded text-sm"
              />
            </div>
            <div className="flex gap-2 text-sm">
              <button
                onClick={save}
                disabled={
                  busy ||
                  !editor.term.trim() ||
                  (!editor.answererExpansion.trim() && !editor.shortGloss.trim())
                }
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
      ) : items.length === 0 && editor?.id !== "new" ? (
        <div className="text-ink-soft py-8 text-center">
          המילון ריק. הוסף מונח ראשון.
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((it) => {
            const isLearnedPending =
              it.source === "learned" && it.status === "pending";
            const evidence = (it.evidence || {}) as {
              from_question?: string;
              to_question?: string;
              why?: string;
              signal_type?: string;
              candidate_term?: string;
              distinct_query_count?: number;
              edited_answer_snippet?: string;
            };
            const approveLearned = async (
              newStatus: "active" | "rejected",
            ) => {
              setBusy(true);
              try {
                await api.updateLexicon(it.id, { status: newStatus });
                await load();
              } catch (err) {
                setError(err instanceof Error ? err.message : String(err));
              } finally {
                setBusy(false);
              }
            };
            return (
              <div
                key={it.id}
                className={`bg-white border rounded-md p-4 ${
                  isLearnedPending ? "border-accent" : "border-line"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-ink">{it.term}</span>
                      <span className="text-[10px] tracking-widest uppercase text-ink-soft">
                        {ENTRY_TYPE_LABELS[it.entry_type] || "הגדרה"}
                      </span>
                      {it.source === "learned" && (
                        <span
                          className={`text-[10px] tracking-[0.2em] uppercase font-bold ${
                            it.status === "pending"
                              ? "text-accent"
                              : "text-ink-soft"
                          }`}
                        >
                          {it.status === "pending"
                            ? "נלמד · ממתין"
                            : it.status === "rejected"
                              ? "נלמד · נדחה"
                              : "נלמד"}
                          {typeof it.confidence === "number"
                            ? ` · ${Math.round(it.confidence * 100)}%`
                            : ""}
                          {evidence.signal_type
                            ? ` · ${evidence.signal_type}`
                            : ""}
                        </span>
                      )}
                      {it.status === "active" && (
                        <span className="text-[10px] tracking-widest uppercase text-emerald-700 font-bold">
                          פעיל · {it.match_count_30d} התאמות ב-30 יום
                        </span>
                      )}
                      {it.status === "active" &&
                        it.match_count_30d === 0 && (
                          <span className="text-[10px] tracking-widest uppercase text-amber-700 font-bold">
                            רשומה מתה?
                          </span>
                        )}
                    </div>
                    {it.short_gloss && (
                      <div className="text-sm text-ink mt-1">
                        {it.short_gloss}
                      </div>
                    )}
                    <div className="text-xs text-ink-soft mt-1 whitespace-pre-wrap">
                      {it.answerer_expansion || it.expansion}
                    </div>
                    {it.surface_forms && it.surface_forms.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {it.surface_forms.slice(0, 8).map((f, i) => (
                          <span
                            key={`${f}-${i}`}
                            className="text-[10px] px-1.5 py-0.5 bg-stone-50 border border-line rounded text-ink-soft"
                          >
                            {f}
                          </span>
                        ))}
                        {it.surface_forms.length > 8 && (
                          <span className="text-[10px] text-ink-soft self-center">
                            +{it.surface_forms.length - 8}
                          </span>
                        )}
                      </div>
                    )}
                    <div className="text-[10px] text-ink-soft mt-2">
                      התאמה אחרונה: {formatRelativeDate(it.last_matched_at)}
                    </div>
                    {it.notes && (
                      <div className="text-xs text-ink-soft mt-2 italic">
                        {it.notes}
                      </div>
                    )}
                    {isLearnedPending &&
                      (evidence.from_question ||
                        evidence.to_question ||
                        evidence.candidate_term ||
                        evidence.edited_answer_snippet) && (
                        <details className="mt-3 text-xs text-ink-soft">
                          <summary className="cursor-pointer hover:text-ink">
                            מקור הזיהוי
                          </summary>
                          <div className="mt-2 space-y-1.5 border-r-2 border-line pr-3">
                            {evidence.from_question && (
                              <div>
                                <span className="font-bold text-ink-soft">
                                  תור 1:
                                </span>{" "}
                                {evidence.from_question}
                              </div>
                            )}
                            {evidence.to_question && (
                              <div>
                                <span className="font-bold text-ink-soft">
                                  תור 2:
                                </span>{" "}
                                {evidence.to_question}
                              </div>
                            )}
                            {evidence.candidate_term && (
                              <div>
                                <span className="font-bold text-ink-soft">
                                  מועמד:
                                </span>{" "}
                                "{evidence.candidate_term}"
                                {typeof evidence.distinct_query_count ===
                                  "number" &&
                                  ` · ב-${evidence.distinct_query_count} תשובות שונות`}
                              </div>
                            )}
                            {evidence.edited_answer_snippet && (
                              <div>
                                <span className="font-bold text-ink-soft">
                                  מתוך עריכת סוקר:
                                </span>{" "}
                                {evidence.edited_answer_snippet}
                              </div>
                            )}
                            {evidence.why && (
                              <div className="italic">{evidence.why}</div>
                            )}
                          </div>
                        </details>
                      )}
                  </div>
                  <div className="flex flex-col gap-1 shrink-0">
                    {isLearnedPending ? (
                      <>
                        <button
                          onClick={() => void approveLearned("active")}
                          disabled={busy}
                          className="text-xs px-2 py-1 text-accent hover:bg-accent/10 rounded font-bold"
                        >
                          ✓ אשר
                        </button>
                        <button
                          onClick={() => void approveLearned("rejected")}
                          disabled={busy}
                          className="text-xs px-2 py-1 text-ink-soft hover:bg-stone-100 rounded"
                        >
                          דחה
                        </button>
                        <button
                          onClick={() => setEditor(editorFromItem(it))}
                          className="text-xs px-2 py-1 text-ink-soft hover:bg-accent/10 rounded"
                        >
                          ערוך
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => setEditor(editorFromItem(it))}
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
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
