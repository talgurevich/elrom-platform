import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  api,
  type LexiconEntryType,
  type LexiconItem,
  type LexiconSuggestion,
} from "../lib/api";
import {
  Chip,
  DsTag,
  DsInput,
  DsSelect,
  StatusPill,
  TrashIcon,
  PencilIcon,
  PlusIcon,
  CheckMarkIcon,
} from "../components/klaser-ds";

/* Field wrapper — teal Rubik label above a DS control. */
function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <div className="font-rubik font-medium text-xs text-turquoise mb-2 flex items-baseline gap-2 justify-start">
        <span>{label}</span>
        {hint && <span className="text-ink-soft font-normal">{hint}</span>}
      </div>
      {children}
    </label>
  );
}

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
    <Field label={`צורות שטח (${forms.length})`} hint="כל וריאציה תיתפס במטצ'ר">
      {forms.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {forms.map((f, i) => (
            <span
              key={`${f}-${i}`}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-line text-ink-soft font-rubik text-xs"
            >
              <span className={i === 0 ? "font-bold text-ink" : ""}>{f}</span>
              <button
                type="button"
                onClick={() => removeAt(i)}
                className="text-ink-soft hover:text-danger transition"
                aria-label="הסר צורה"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <div className="flex-1">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            placeholder="למשל: השיוכים"
            className="w-full px-3 py-2.5 border border-line rounded-md bg-white text-sm text-ink font-rubik text-right outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
          />
        </div>
        <Chip variant="teal-outline" onClick={add} disabled={!draft.trim()}>
          הוסף
        </Chip>
      </div>
    </Field>
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
      <header className="mb-10 flex items-end justify-between flex-wrap gap-4">
        <div className="text-right">
          <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-4">
            לקסיקון
          </div>
          <h1 className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px] text-ink">
            מילון מונחים
          </h1>
          <p className="mt-4 text-lg text-ink-soft max-w-2xl leading-relaxed">
            מונחים תחומיים שהארגון מסביר ל-AI לפני שהוא עונה — כדי שמילים
            ייחודיות לא תפורשנה לא נכון. כל מונח נמדד לפי מספר הפעמים שהופעל
            ב-30 הימים האחרונים כדי לזהות רשומות מתות.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Chip
            variant="grey"
            onClick={generateSuggestions}
            disabled={suggesting}
          >
            {suggesting ? "מנתח..." : "הצע מתוך שאלות שנכשלו"}
          </Chip>
          {editor === null && (
            <button
              onClick={() => setEditor(emptyEditor())}
              className="inline-flex items-center gap-2 bg-turquoise text-white h-10 px-5 rounded-md font-rubik font-bold text-sm hover:bg-turquoise-dark transition"
            >
              <span>הוסף מונח</span>
              <PlusIcon />
            </button>
          )}
        </div>
      </header>

      {suggestions !== null && (
        <div className="mb-6 p-6 bg-white border border-line rounded-lg">
          <div className="font-rubik font-bold text-sm text-turquoise mb-4">
            הצעות מתוך {suggestions.length} שאלות שנכשלו לאחרונה
          </div>
          {suggestions.length === 0 ? (
            <div className="text-sm text-ink-soft leading-relaxed">
              לא נמצאו מועמדים חדשים. יש גם קציר אוטומטי לילי מציטוטים ומראשי תיבות
              בתשובות — הרשומות המוצעות יופיעו כרשומות "נלמד · ממתין" למטה.
            </div>
          ) : (
            <div className="space-y-3">
              {suggestions.map((s) => (
                <div
                  key={s.term}
                  className="flex items-start justify-between gap-3 p-4 bg-turquoise/5 rounded-md"
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-rubik font-bold text-sm text-ink">{s.term}</div>
                    <div className="text-sm text-ink mt-1">{s.expansion}</div>
                    <div className="text-xs text-ink-soft mt-1 italic">
                      מתוך: "{s.source_question}"
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button
                      onClick={() => acceptSuggestion(s)}
                      disabled={busy}
                      className="inline-flex items-center bg-turquoise text-white h-9 px-4 rounded-md font-rubik font-bold text-xs hover:bg-turquoise-dark transition disabled:opacity-50"
                    >
                      קבל
                    </button>
                    <button
                      onClick={() =>
                        setSuggestions((cur) =>
                          cur ? cur.filter((x) => x.term !== s.term) : cur,
                        )
                      }
                      className="inline-flex items-center px-3 py-1.5 rounded-md bg-line text-ink-soft hover:bg-line-strong font-rubik font-medium text-xs transition"
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
        <div className="mb-4 p-3 bg-danger/10 border border-danger/30 rounded-md text-danger text-sm font-rubik">
          {error}
        </div>
      )}

      {editor && (
        <div className="mb-6 p-8 bg-white border border-line rounded-lg shadow-[0px_1px_0_rgba(0,0,0,0.03),0px_4px_16px_-4px_rgba(0,0,0,0.06)]">
          <div className="grid gap-5">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="md:col-span-2">
                <Field label="מונח קנוני">
                  <DsInput
                    value={editor.term}
                    onChange={(v) => setEditor({ ...editor, term: v })}
                    placeholder='למשל: "שיוך"'
                  />
                </Field>
              </div>
              <Field label="סוג רשומה">
                <DsSelect
                  value={editor.entryType}
                  onChange={(v) =>
                    setEditor({
                      ...editor,
                      entryType: v as LexiconEntryType,
                    })
                  }
                >
                  {(Object.keys(ENTRY_TYPE_LABELS) as LexiconEntryType[]).map(
                    (k) => (
                      <option key={k} value={k}>
                        {ENTRY_TYPE_LABELS[k]}
                      </option>
                    ),
                  )}
                </DsSelect>
              </Field>
            </div>
            <SurfaceFormsEditor
              forms={editor.surfaceForms}
              onChange={(next) => setEditor({ ...editor, surfaceForms: next })}
            />
            <Field label="הסבר קצר" hint="לתצוגה על ריחוף בתשובה">
              <DsInput
                value={editor.shortGloss}
                onChange={(v) => setEditor({ ...editor, shortGloss: v })}
                placeholder="משפט אחד קצר להסבר על ריחוף"
              />
            </Field>
            <Field label="הרחבה למענה" hint="יוטמע ב-PROMPT ל-AI">
              <textarea
                value={editor.answererExpansion}
                onChange={(e) =>
                  setEditor({ ...editor, answererExpansion: e.target.value })
                }
                rows={4}
                placeholder="למשל: המעבר מקיבוץ שיתופי לקיבוץ מתחדש; ראה תקנון שיוך פירות נכסים..."
                className="w-full px-3 py-2.5 border border-line rounded-md bg-white text-sm text-ink font-rubik text-right leading-relaxed outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
              />
            </Field>
            <Field label="הערות פנימיות">
              <textarea
                value={editor.notes}
                onChange={(e) =>
                  setEditor({ ...editor, notes: e.target.value })
                }
                rows={2}
                className="w-full px-3 py-2.5 border border-line rounded-md bg-white text-sm text-ink font-rubik text-right outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
              />
            </Field>
            <div className="flex items-center gap-3 pt-2 flex-row-reverse justify-end">
              <button
                onClick={save}
                disabled={
                  busy ||
                  !editor.term.trim() ||
                  (!editor.answererExpansion.trim() && !editor.shortGloss.trim())
                }
                className="inline-flex items-center bg-turquoise text-white h-10 px-6 rounded-md font-rubik font-bold text-sm hover:bg-turquoise-dark transition disabled:opacity-50"
              >
                שמור
              </button>
              <button
                onClick={cancel}
                className="inline-flex items-center h-10 px-4 rounded-md text-sm text-ink-soft font-rubik font-medium hover:text-ink hover:bg-line/60 transition"
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
                className={`bg-white rounded-lg p-5 border shadow-[0px_1px_0_rgba(0,0,0,0.03),0px_4px_16px_-4px_rgba(0,0,0,0.06)] transition ${
                  isLearnedPending ? "border-turquoise/40" : "border-line"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    {/* Title row — term + status text on the right, meta chips on the left */}
                    <div className="flex items-center gap-3 flex-wrap justify-start">
                      <span className="font-rubik font-bold text-lg text-ink">{it.term}</span>
                      {it.status === "active" && (
                        <span className="font-rubik text-sm text-turquoise">
                          פעיל · {it.match_count_30d} התאמות ב-30 יום
                        </span>
                      )}
                      {it.status === "active" &&
                        it.match_count_30d === 0 && (
                          <StatusPill variant="warning">רשומה מתה?</StatusPill>
                        )}
                      <DsTag>{ENTRY_TYPE_LABELS[it.entry_type] || "הגדרה"}</DsTag>
                      {it.source === "learned" && (
                        <StatusPill
                          variant={it.status === "pending" ? "teal" : "neutral"}
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
                        </StatusPill>
                      )}
                    </div>
                    {it.short_gloss && (
                      <div className="text-base text-ink mt-3 leading-relaxed">
                        {it.short_gloss}
                      </div>
                    )}
                    <div className="text-sm text-ink-soft mt-2 whitespace-pre-wrap leading-relaxed">
                      {it.answerer_expansion || it.expansion}
                    </div>
                    {it.surface_forms && it.surface_forms.length > 0 && (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {it.surface_forms.slice(0, 8).map((f, i) => (
                          <DsTag key={`${f}-${i}`}>{f}</DsTag>
                        ))}
                        {it.surface_forms.length > 8 && (
                          <span className="font-rubik text-xs text-ink-soft self-center">
                            +{it.surface_forms.length - 8}
                          </span>
                        )}
                      </div>
                    )}
                    <div className="text-xs text-ink-soft mt-4 font-rubik">
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
                  <div className="flex gap-2 shrink-0">
                    {isLearnedPending ? (
                      <>
                        <button
                          onClick={() => void approveLearned("active")}
                          disabled={busy}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-turquoise text-turquoise bg-white hover:bg-turquoise hover:text-white transition font-rubik font-medium text-xs disabled:opacity-50"
                        >
                          <CheckMarkIcon />
                          <span>אשר</span>
                        </button>
                        <button
                          onClick={() => void approveLearned("rejected")}
                          disabled={busy}
                          className="inline-flex items-center px-3 py-1.5 rounded-md bg-line text-ink-soft hover:bg-line-strong font-rubik font-medium text-xs transition disabled:opacity-50"
                        >
                          דחה
                        </button>
                        <button
                          onClick={() => setEditor(editorFromItem(it))}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-line-strong text-ink-soft bg-white hover:border-turquoise hover:text-turquoise transition font-rubik font-medium text-xs"
                        >
                          <PencilIcon />
                          <span>ערוך</span>
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => remove(it)}
                          disabled={busy}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-danger text-danger bg-white hover:bg-danger hover:text-white transition font-rubik font-medium text-xs disabled:opacity-50"
                        >
                          <TrashIcon />
                          <span>מחק</span>
                        </button>
                        <button
                          onClick={() => setEditor(editorFromItem(it))}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-line-strong text-ink-soft bg-white hover:border-turquoise hover:text-turquoise transition font-rubik font-medium text-xs"
                        >
                          <PencilIcon />
                          <span>ערוך</span>
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
